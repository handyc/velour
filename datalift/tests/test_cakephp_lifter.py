"""Tests for datalift.cakephp_lifter — CakePHP 4/5 → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.cakephp_lifter import (
    apply, parse_cakephp, parse_controller, parse_routes,
    render_urls, render_views, _convert_path,
)


class PathConversionTests(SimpleTestCase):

    def test_static_path(self):
        path, args = _convert_path('/articles')
        self.assertEqual(path, 'articles/')
        self.assertEqual(args, [])

    def test_id_inferred_int(self):
        path, args = _convert_path('/articles/{id}')
        self.assertEqual(path, 'articles/<int:id>/')

    def test_regex_hint_int(self):
        path, args = _convert_path('/articles/{n}', {'n': '\\d+'})
        self.assertEqual(path, 'articles/<int:n>/')

    def test_named_param_default_str(self):
        path, args = _convert_path('/posts/{slug}')
        self.assertEqual(path, 'posts/<str:slug>/')

    def test_greedy_star(self):
        path, args = _convert_path('/pages/*')
        self.assertEqual(path, 'pages/<path:tail>/')


class RouteParsingTests(SimpleTestCase):

    def test_connect_string_form(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/', function ($builder) {
                    $builder->connect('/pages/*', 'Pages::display');
                });
            };
        """)
        routes, fb = parse_routes(php)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].controller, 'PagesController')
        self.assertEqual(routes[0].action, 'display')
        self.assertEqual(routes[0].path, 'pages/<path:tail>/')

    def test_connect_array_form(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/', function ($builder) {
                    $builder->connect('/articles/{id}',
                        ['controller' => 'Articles', 'action' => 'view']);
                });
            };
        """)
        routes, _ = parse_routes(php)
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].controller, 'ArticlesController')
        self.assertEqual(routes[0].action, 'view')
        self.assertEqual(routes[0].path, 'articles/<int:id>/')

    def test_scope_prepends_path(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/api', function ($builder) {
                    $builder->connect('/articles', 'Articles::index');
                });
            };
        """)
        routes, _ = parse_routes(php)
        self.assertEqual(routes[0].path, 'api/articles/')

    def test_prefix_namespaces_controller(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->prefix('Admin', function ($builder) {
                    $builder->connect('/dashboard',
                        ['controller' => 'Dashboard', 'action' => 'index']);
                });
            };
        """)
        routes, _ = parse_routes(php)
        self.assertEqual(routes[0].controller, 'Admin_DashboardController')
        self.assertEqual(routes[0].action, 'index')

    def test_resources_expansion(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/api', function ($builder) {
                    $builder->resources('Articles');
                });
            };
        """)
        routes, _ = parse_routes(php)
        self.assertEqual(len(routes), 7)
        self.assertEqual({r.controller for r in routes},
                          {'ArticlesController'})
        verbs = sorted({r.http_method for r in routes})
        for v in ('GET', 'POST', 'PUT', 'DELETE'):
            self.assertIn(v, verbs)

    def test_fallbacks_flag(self):
        php = dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/', function ($builder) {
                    $builder->fallbacks();
                });
            };
        """)
        routes, fb = parse_routes(php)
        self.assertTrue(fb)


class ControllerParsingTests(SimpleTestCase):

    def test_basic_controller(self):
        php = dedent("""\
            <?php
            namespace App\\Controller;
            class ArticlesController extends AppController
            {
                public function index() {
                    $articles = $this->Articles->find('all');
                    $this->set(compact('articles'));
                }
                public function view($id) {
                    $article = $this->Articles->get($id);
                    $this->set(compact('article'));
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIsNotNone(ctl)
        self.assertEqual(ctl.class_name, 'ArticlesController')
        self.assertEqual(len(ctl.actions), 2)
        names = [a.name for a in ctl.actions]
        self.assertEqual(names, ['index', 'view'])

    def test_view_action_args(self):
        php = dedent("""\
            <?php
            class ArticlesController extends AppController {
                public function view($id) { }
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.actions[0].args, ['id'])

    def test_lifecycle_methods_skipped(self):
        php = dedent("""\
            <?php
            class FooController extends AppController {
                public function initialize(): void {}
                public function beforeFilter() {}
                public function index() {}
            }
        """)
        ctl = parse_controller(php)
        names = [a.name for a in ctl.actions]
        self.assertEqual(names, ['index'])

    def test_redirect_translation(self):
        php = dedent("""\
            <?php
            class FooController extends AppController {
                public function bar() {
                    return $this->redirect('/');
                }
            }
        """)
        ctl = parse_controller(php)
        # Should not produce 'return return redirect'
        self.assertNotIn('return return', ctl.actions[0].body)
        self.assertIn("return redirect('/')", ctl.actions[0].body)

    def test_request_get_data(self):
        php = dedent("""\
            <?php
            class FooController extends AppController {
                public function bar() {
                    $name = $this->request->getData('name');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("request.POST.get('name')", ctl.actions[0].body)

    def test_render_translation(self):
        php = dedent("""\
            <?php
            class PagesController extends AppController {
                public function display($name) {
                    return $this->render('Pages/home');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("render(request, 'Pages/home.html')",
                      ctl.actions[0].body)

    def test_prefix_qualifies_class_name(self):
        php = dedent("""\
            <?php
            namespace App\\Controller\\Admin;
            class DashboardController extends AppController {
                public function index() {}
            }
        """)
        ctl = parse_controller(php, prefix='Admin')
        self.assertEqual(ctl.qualified_name, 'Admin_DashboardController')

    def test_non_controller_skipped(self):
        php = "<?php class JustAClass {}"
        self.assertIsNone(parse_controller(php))


class FileWalkerTests(SimpleTestCase):

    def test_parse_minimal_skeleton(self):
        tmp = Path(tempfile.mkdtemp()) / 'app'
        (tmp / 'config').mkdir(parents=True)
        (tmp / 'src' / 'Controller').mkdir(parents=True)
        (tmp / 'config' / 'routes.php').write_text(dedent("""\
            <?php
            return function ($routes) {
                $routes->scope('/', function ($builder) {
                    $builder->connect('/', ['controller' => 'Pages',
                        'action' => 'display', 'home']);
                    $builder->connect('/pages/*', 'Pages::display');
                    $builder->fallbacks();
                });
            };
        """))
        (tmp / 'src' / 'Controller' / 'AppController.php').write_text(
            "<?php\nnamespace App\\Controller;\n"
            "class AppController extends Controller {}"
        )
        (tmp / 'src' / 'Controller' / 'PagesController.php').write_text(dedent("""\
            <?php
            namespace App\\Controller;
            class PagesController extends AppController {
                public function display() {
                    return $this->render('home');
                }
            }
        """))
        result = parse_cakephp(tmp)
        self.assertEqual(len(result.routes), 2)
        self.assertEqual(len(result.controllers), 1)
        # AppController must be filtered out as a base class.
        self.assertEqual(result.controllers[0].class_name, 'PagesController')
        self.assertTrue(result.fallbacks_used)

    def test_admin_prefix_picked_up(self):
        tmp = Path(tempfile.mkdtemp()) / 'app'
        (tmp / 'src' / 'Controller' / 'Admin').mkdir(parents=True)
        (tmp / 'src' / 'Controller' / 'Admin' / 'DashboardController.php'
         ).write_text(dedent("""\
             <?php
             namespace App\\Controller\\Admin;
             class DashboardController extends AppController {
                 public function index() {}
             }
         """))
        result = parse_cakephp(tmp)
        self.assertEqual(len(result.controllers), 1)
        self.assertEqual(result.controllers[0].qualified_name,
                          'Admin_DashboardController')


class RenderingTests(SimpleTestCase):

    def test_render_urls_emits_paths(self):
        from datalift.cakephp_lifter import CakeLiftResult, CakeRoute
        result = CakeLiftResult(routes=[
            CakeRoute(http_method='ANY', path='articles/<int:id>/',
                      controller='ArticlesController', action='view'),
        ])
        text = render_urls(result, 'app')
        self.assertIn(
            "path('articles/<int:id>/', views.ArticlesController_view)",
            text,
        )

    def test_render_urls_dispatch(self):
        from datalift.cakephp_lifter import CakeLiftResult, CakeRoute
        result = CakeLiftResult(routes=[
            CakeRoute(http_method='GET', path='login/',
                      controller='AuthController', action='login'),
            CakeRoute(http_method='POST', path='login/',
                      controller='AuthController', action='attemptLogin'),
        ])
        text = render_urls(result, 'app')
        self.assertIn('_dispatch_login', text)
        self.assertIn("if method == 'GET'", text)
        self.assertIn("if method == 'POST'", text)

    def test_render_urls_fallback_marker(self):
        from datalift.cakephp_lifter import CakeLiftResult
        result = CakeLiftResult(fallbacks_used=True)
        text = render_urls(result, 'app')
        self.assertIn('PORTER', text)
        self.assertIn('fallbacks()', text)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_outputs(self):
        from datalift.cakephp_lifter import (
            CakeLiftResult, CakeRoute, CakeController, CakeAction,
        )
        tmp = Path(tempfile.mkdtemp()); proj = tmp / 'proj'; proj.mkdir()
        result = CakeLiftResult(
            routes=[CakeRoute(http_method='ANY', path='',
                              controller='PagesController',
                              action='display')],
            controllers=[CakeController(
                source=Path('PagesController.php'),
                class_name='PagesController',
                qualified_name='PagesController',
                actions=[CakeAction(name='display', args=[],
                                     body="return HttpResponse('ok')",
                                     raw_body='')],
            )],
        )
        apply(result, proj, 'myapp')
        urls = (proj / 'myapp' / 'urls_cakephp.py').read_text()
        views = (proj / 'myapp' / 'views_cakephp.py').read_text()
        self.assertIn("path('', views.PagesController_display)", urls)
        self.assertIn('def PagesController_display(request):', views)
