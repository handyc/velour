"""Tests for datalift.codeigniter_lifter — CI3+CI4 → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.codeigniter_lifter import (
    apply, parse_codeigniter, parse_controller, parse_routes_ci3,
    parse_routes_ci4, render_urls, render_views,
    _convert_path,
)


class PathConversionTests(SimpleTestCase):

    def test_static_path(self):
        path, args = _convert_path('users')
        self.assertEqual(path, 'users/')
        self.assertEqual(args, [])

    def test_num_placeholder(self):
        path, args = _convert_path('users/(:num)')
        self.assertEqual(path, 'users/<int:arg1>/')
        self.assertEqual(args, ['arg1'])

    def test_any_placeholder(self):
        path, args = _convert_path('catalog/(:any)')
        self.assertEqual(path, 'catalog/<str:arg1>/')

    def test_segment_placeholder(self):
        path, args = _convert_path('posts/(:segment)')
        self.assertEqual(path, 'posts/<slug:arg1>/')

    def test_two_placeholders(self):
        path, args = _convert_path('blog/(:num)/(:segment)')
        self.assertEqual(path, 'blog/<int:arg1>/<slug:arg2>/')


class CI3RouteTests(SimpleTestCase):

    def test_basic_routes(self):
        php = dedent("""\
            <?php
            $route['default_controller'] = 'welcome';
            $route['users/(:num)'] = 'users/show/$1';
            $route['products/(:any)'] = 'catalog/product/$1';
        """)
        routes = parse_routes_ci3(php)
        self.assertEqual(len(routes), 2)
        r0 = routes[0]
        self.assertEqual(r0.path, 'users/<int:arg1>/')
        self.assertEqual(r0.controller, 'Users')
        self.assertEqual(r0.method, 'show')
        r1 = routes[1]
        self.assertEqual(r1.controller, 'Catalog')
        self.assertEqual(r1.method, 'product')


class CI4RouteTests(SimpleTestCase):

    def test_get_root(self):
        routes = parse_routes_ci4("<?php\n$routes->get('/', 'Home::index');")
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].http_method, 'GET')
        self.assertEqual(routes[0].path, '')
        self.assertEqual(routes[0].controller, 'Home')
        self.assertEqual(routes[0].method, 'index')

    def test_get_with_param(self):
        routes = parse_routes_ci4(
            "<?php\n$routes->get('users/(:num)', 'Users::show/$1');"
        )
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].path, 'users/<int:arg1>/')

    def test_post_route(self):
        routes = parse_routes_ci4(
            "<?php\n$routes->post('login', 'Auth::attempt');"
        )
        self.assertEqual(routes[0].http_method, 'POST')

    def test_named_route(self):
        routes = parse_routes_ci4(
            "<?php\n$routes->get('login', 'Auth::login', ['as' => 'login']);"
        )
        self.assertEqual(routes[0].name, 'login')

    def test_resource_expansion(self):
        routes = parse_routes_ci4(
            "<?php\n$routes->resource('photos');"
        )
        # CI4 resource → 7 standard REST routes
        self.assertEqual(len(routes), 7)
        verbs = sorted(r.http_method for r in routes)
        self.assertIn('GET', verbs)
        self.assertIn('POST', verbs)
        self.assertIn('PUT', verbs)
        self.assertIn('DELETE', verbs)
        # Every route's controller is 'Photos'
        self.assertEqual({r.controller for r in routes}, {'Photos'})

    def test_group_prefix(self):
        php = dedent("""\
            <?php
            $routes->group('admin', static function ($routes) {
                $routes->get('/', 'Admin::index');
                $routes->get('users', 'Admin::users');
            });
        """)
        routes = parse_routes_ci4(php)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0].path, 'admin/')
        self.assertEqual(routes[1].path, 'admin/users/')

    def test_group_namespace_prefix(self):
        php = dedent("""\
            <?php
            $routes->group('', ['namespace' => 'Myth\\Auth\\Controllers'],
                static function ($routes) {
                    $routes->get('login', 'AuthController::login');
                });
        """)
        routes = parse_routes_ci4(php)
        self.assertEqual(len(routes), 1)
        # Namespace prefix should be 'Myth_Auth' (Controllers stripped).
        self.assertEqual(routes[0].controller, 'Myth_Auth_AuthController')


class ControllerParsingTests(SimpleTestCase):

    def test_ci3_controller(self):
        php = dedent("""\
            <?php
            class Welcome extends CI_Controller {
                public function index() {
                    $this->load->view('welcome_message');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIsNotNone(ctl)
        self.assertEqual(ctl.class_name, 'Welcome')
        self.assertEqual(len(ctl.methods), 1)
        self.assertEqual(ctl.methods[0].name, 'index')
        # Body translation
        self.assertIn("render(request, 'welcome_message.html')",
                      ctl.methods[0].body)

    def test_ci4_namespaced_controller(self):
        php = dedent("""\
            <?php
            namespace App\\Controllers;
            class Home extends BaseController {
                public function index(): string {
                    return view('welcome_message');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.class_name, 'Home')
        # Method present
        self.assertEqual(len(ctl.methods), 1)
        self.assertIn("render(request, 'welcome_message.html')",
                      ctl.methods[0].body)

    def test_method_with_args(self):
        php = dedent("""\
            <?php
            class Users extends CI_Controller {
                public function show($id) {
                    $this->load->view('users/show');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.methods[0].args, ['id'])

    def test_post_input_translation(self):
        php = dedent("""\
            <?php
            class Auth extends CI_Controller {
                public function login() {
                    $email = $this->input->post('email');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("request.POST.get('email')", ctl.methods[0].body)

    def test_redirect_translation(self):
        php = dedent("""\
            <?php
            class Auth extends CI_Controller {
                public function logout() {
                    redirect('login');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("return redirect('/login/')", ctl.methods[0].body)

    def test_redirect_with_existing_return_no_double(self):
        php = dedent("""\
            <?php
            class Auth extends CI_Controller {
                public function login() {
                    return redirect('home');
                }
            }
        """)
        ctl = parse_controller(php)
        # Should NOT produce 'return return redirect(...)'
        self.assertNotIn('return return', ctl.methods[0].body)
        self.assertIn("return redirect('/home/')", ctl.methods[0].body)

    def test_session_userdata(self):
        php = dedent("""\
            <?php
            class Profile extends CI_Controller {
                public function index() {
                    $name = $this->session->userdata('name');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("request.session.get('name')", ctl.methods[0].body)

    def test_underscore_methods_skipped(self):
        php = dedent("""\
            <?php
            class Foo extends CI_Controller {
                public function _internal() {}
                public function index() {}
            }
        """)
        ctl = parse_controller(php)
        names = [m.name for m in ctl.methods]
        self.assertEqual(names, ['index'])

    def test_non_controller_skipped(self):
        php = "<?php class JustALib { public function whatever() {} }"
        self.assertIsNone(parse_controller(php))


class FileWalkerTests(SimpleTestCase):

    def test_parse_ci3_layout(self):
        tmp = Path(tempfile.mkdtemp()) / 'app'
        (tmp / 'application' / 'controllers').mkdir(parents=True)
        (tmp / 'application' / 'config').mkdir(parents=True)
        (tmp / 'application' / 'config' / 'routes.php').write_text(
            "<?php\n$route['default_controller'] = 'welcome';\n"
            "$route['users/(:num)'] = 'users/show/$1';\n"
        )
        (tmp / 'application' / 'controllers' / 'Welcome.php').write_text(
            "<?php\nclass Welcome extends CI_Controller {\n"
            "    public function index() {\n"
            "        $this->load->view('welcome_message');\n"
            "    }\n}\n"
        )
        result = parse_codeigniter(tmp)
        self.assertEqual(len(result.routes), 1)
        self.assertEqual(len(result.controllers), 1)

    def test_parse_ci4_layout(self):
        tmp = Path(tempfile.mkdtemp()) / 'app'
        (tmp / 'app' / 'Controllers').mkdir(parents=True)
        (tmp / 'app' / 'Config').mkdir(parents=True)
        (tmp / 'app' / 'Config' / 'Routes.php').write_text(
            "<?php\n$routes->get('/', 'Home::index');\n"
        )
        (tmp / 'app' / 'Controllers' / 'Home.php').write_text(
            "<?php\nnamespace App\\Controllers;\n"
            "class Home extends BaseController {\n"
            "    public function index(): string {\n"
            "        return view('welcome_message');\n"
            "    }\n}\n"
        )
        result = parse_codeigniter(tmp)
        self.assertEqual(len(result.routes), 1)
        self.assertEqual(len(result.controllers), 1)


class RenderingTests(SimpleTestCase):

    def test_render_urls_basic(self):
        from datalift.codeigniter_lifter import CILiftResult, CIRoute
        result = CILiftResult(routes=[
            CIRoute(http_method='GET', path='users/<int:arg1>/',
                    controller='Users', method='show'),
        ])
        text = render_urls(result, 'app')
        self.assertIn("path('users/<int:arg1>/', views.Users_show)", text)

    def test_render_urls_dispatch_for_shared_path(self):
        from datalift.codeigniter_lifter import CILiftResult, CIRoute
        result = CILiftResult(routes=[
            CIRoute(http_method='GET', path='login/',
                    controller='Auth', method='login'),
            CIRoute(http_method='POST', path='login/',
                    controller='Auth', method='attemptLogin'),
        ])
        text = render_urls(result, 'app')
        self.assertIn('_dispatch_login', text)
        self.assertIn("if method == 'GET'", text)
        self.assertIn("if method == 'POST'", text)

    def test_render_views_emits_function(self):
        from datalift.codeigniter_lifter import (
            CILiftResult, CIController, CIMethod,
        )
        result = CILiftResult(controllers=[
            CIController(source=Path('Foo.php'), class_name='Foo',
                          qualified_name='Foo',
                          methods=[CIMethod(name='index', args=[],
                                             body='return HttpResponse(\'hi\')',
                                             raw_body='')]),
        ])
        text = render_views(result)
        self.assertIn('def Foo_index(request):', text)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_outputs(self):
        from datalift.codeigniter_lifter import (
            CILiftResult, CIController, CIMethod, CIRoute,
        )
        tmp = Path(tempfile.mkdtemp())
        proj = tmp / 'proj'; proj.mkdir()
        result = CILiftResult(
            routes=[CIRoute(http_method='GET', path='', controller='Home',
                            method='index')],
            controllers=[CIController(
                source=Path('Home.php'), class_name='Home',
                qualified_name='Home',
                methods=[CIMethod(name='index', args=[],
                                   body="return HttpResponse('ok')",
                                   raw_body='')]),
            ],
        )
        apply(result, proj, 'myapp')
        urls = (proj / 'myapp' / 'urls_codeigniter.py').read_text()
        views = (proj / 'myapp' / 'views_codeigniter.py').read_text()
        self.assertIn("path('', views.Home_index", urls)
        self.assertIn('def Home_index(request):', views)
