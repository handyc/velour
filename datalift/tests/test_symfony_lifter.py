"""Tests for datalift.symfony_lifter — Symfony controllers + routes → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.symfony_lifter import (
    apply, parse_controller, parse_symfony, parse_yaml_routes,
    render_urls, render_views, render_worklist,
    symfony_path_to_django, translate_method_body,
)


class PathTranslationTests(SimpleTestCase):

    def test_static_path(self):
        self.assertEqual(symfony_path_to_django('/users'), 'users/')

    def test_int_param(self):
        self.assertEqual(symfony_path_to_django('/users/{id}'),
                         'users/<int:id>/')

    def test_slug_param(self):
        self.assertEqual(symfony_path_to_django('/posts/{slug}'),
                         'posts/<slug:slug>/')

    def test_param_with_digit_requirement(self):
        self.assertEqual(symfony_path_to_django(r'/users/{id<\d+>}'),
                         'users/<int:id>/')

    def test_param_with_letter_requirement(self):
        self.assertEqual(symfony_path_to_django('/posts/{slug<[a-z-]+>}'),
                         'posts/<slug:slug>/')


class AttributeRouteTests(SimpleTestCase):

    def test_simple_attribute_route(self):
        php = dedent("""\
            <?php
            namespace App\\Controller;
            class UserController {
                #[Route('/users', name: 'app_user_index', methods: ['GET'])]
                public function index() {
                    return $this->render('user/index.html.twig', ['users' => []]);
                }
            }
        """)
        rec = parse_controller(php)
        self.assertEqual(rec.class_name, 'UserController')
        self.assertEqual(rec.namespace, 'App\\Controller')
        self.assertEqual(len(rec.methods), 1)
        m = rec.methods[0]
        self.assertEqual(len(m.routes), 1)
        self.assertEqual(m.routes[0].method, 'GET')
        self.assertEqual(m.routes[0].path, '/users')
        self.assertEqual(m.routes[0].name, 'app_user_index')

    def test_attribute_with_path_kwarg(self):
        php = dedent("""\
            <?php
            class C {
                #[Route(path: '/x', name: 'r')]
                public function f() { return new Response(); }
            }
        """)
        rec = parse_controller(php)
        self.assertEqual(rec.methods[0].routes[0].path, '/x')

    def test_class_level_route_prefix(self):
        """Symfony commonly puts a #[Route('/admin/blog')] on the
        controller class itself; method routes are prepended by that
        prefix. Also applies to the route name prefix."""
        php = dedent("""\
            <?php
            namespace App\\Controller;
            #[Route('/admin/blog', name: 'admin_post_')]
            class BlogController {
                #[Route('/', methods: ['GET'], name: 'index')]
                public function index() {}

                #[Route('/{id<\\\\d+>}/edit', methods: ['GET', 'POST'], name: 'edit')]
                public function edit($id) {}
            }
        """)
        rec = parse_controller(php)
        # Two methods, three routes (edit has GET and POST).
        idx = next(m for m in rec.methods if m.name == 'index')
        edt = next(m for m in rec.methods if m.name == 'edit')
        # Class prefix '/admin/blog' + method '/' = '/admin/blog'
        self.assertEqual(idx.routes[0].path, '/admin/blog')
        self.assertTrue(edt.routes[0].path.startswith('/admin/blog/'))
        self.assertIn('id', edt.routes[0].path)
        # Names get the class prefix too.
        self.assertEqual(idx.routes[0].name, 'admin_post_index')
        self.assertEqual(edt.routes[0].name, 'admin_post_edit')

    def test_attribute_multiple_methods(self):
        php = dedent("""\
            <?php
            class C {
                #[Route('/items/{id}', methods: ['GET', 'POST'])]
                public function show($id) {}
            }
        """)
        rec = parse_controller(php)
        methods = sorted(r.method for r in rec.methods[0].routes)
        self.assertEqual(methods, ['GET', 'POST'])


class AnnotationRouteTests(SimpleTestCase):

    def test_docblock_annotation(self):
        php = dedent("""\
            <?php
            namespace App\\Controller;
            class UserController {
                /**
                 * @Route("/users", name="app_user_index", methods={"GET"})
                 */
                public function index() {
                    return $this->render('user/index.html.twig');
                }
            }
        """)
        rec = parse_controller(php)
        self.assertEqual(len(rec.methods[0].routes), 1)
        r = rec.methods[0].routes[0]
        self.assertEqual(r.path, '/users')
        self.assertEqual(r.method, 'GET')


class YAMLRouteTests(SimpleTestCase):

    def test_simple_yaml_route(self):
        yaml = dedent("""\
            app_user_index:
                path: /users
                controller: App\\Controller\\UserController::index
                methods: [GET]

            app_user_show:
                path: /users/{id}
                controller: App\\Controller\\UserController::show
                methods: [GET]
        """)
        routes = parse_yaml_routes(yaml)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0].path, '/users')
        self.assertEqual(routes[0].name, 'app_user_index')
        self.assertEqual(routes[0].controller, 'UserController')
        self.assertEqual(routes[0].action, 'index')


class BodyTranslationTests(SimpleTestCase):

    def test_render(self):
        php = "return $this->render('user/index.html.twig', ['x' => $x]);"
        out, _ = translate_method_body(php)
        self.assertIn("render(request, 'user/index.html'", out)

    def test_redirect_to_route(self):
        php = "return $this->redirectToRoute('app_user_index');"
        out, _ = translate_method_body(php)
        self.assertIn("redirect('app_user_index')", out)

    def test_json_response(self):
        php = "return $this->json($data);"
        out, _ = translate_method_body(php)
        self.assertIn("JsonResponse(data)", out)

    def test_get_user(self):
        php = "$user = $this->getUser();"
        out, _ = translate_method_body(php)
        self.assertIn("user = request.user", out)

    def test_doctrine_findall(self):
        php = "$users = $userRepository->findAll();"
        out, _ = translate_method_body(php)
        self.assertIn("userRepository.objects.all()", out)

    def test_doctrine_find(self):
        php = "$user = $userRepository->find($id);"
        out, _ = translate_method_body(php)
        self.assertIn("filter(id=id).first()", out)

    def test_doctrine_findoneby(self):
        php = "$user = $userRepository->findOneBy(['email' => $email]);"
        out, _ = translate_method_body(php)
        self.assertIn("filter(**", out)
        self.assertIn(".first()", out)

    def test_request_get_query(self):
        php = "$page = $request->query->get('page');"
        out, _ = translate_method_body(php)
        self.assertIn("request.GET.get('page')", out)

    def test_request_get_post(self):
        php = "$name = $request->request->get('name');"
        out, _ = translate_method_body(php)
        self.assertIn("request.POST.get('name')", out)

    def test_persist_flush(self):
        php = "$em->persist($user); $em->flush();"
        out, _ = translate_method_body(php)
        self.assertIn("user.save()", out)


class WalkerTests(SimpleTestCase):

    def test_parse_symfony_directory(self):
        tmp = Path(tempfile.mkdtemp())
        app = tmp / 'symfony'
        # Controller
        (app / 'src' / 'Controller').mkdir(parents=True)
        (app / 'src' / 'Controller' / 'UserController.php').write_text(dedent("""\
            <?php
            namespace App\\Controller;
            class UserController {
                #[Route('/users', name: 'app_user_index')]
                public function index() {
                    return $this->render('user/index.html.twig');
                }
            }
        """))
        # YAML route file
        (app / 'config' / 'routes').mkdir(parents=True)
        (app / 'config' / 'routes' / 'main.yaml').write_text(dedent("""\
            app_homepage:
                path: /
                controller: App\\Controller\\HomeController::index
                methods: [GET]
        """))
        result = parse_symfony(app)
        self.assertEqual(len(result.controllers), 1)
        self.assertEqual(len(result.yaml_routes), 1)


class RenderingTests(SimpleTestCase):

    def test_render_views(self):
        from datalift.symfony_lifter import (
            SymfonyController, SymfonyMethod,
        )
        ctrl = SymfonyController(
            source=Path('UserController.php'),
            class_name='UserController',
            methods=[SymfonyMethod(
                name='index', visibility='public', args=[],
                body_php='', body_django=("users = userRepository.objects.all()\n"
                                          "return render(request, 'user/index.html', "
                                          "{'users': users})"),
            )],
        )
        text = render_views([ctrl])
        self.assertIn('def UserController_index(request):', text)
        self.assertIn("render(request, 'user/index.html'", text)

    def test_render_urls_with_attribute_routes(self):
        php = dedent("""\
            <?php
            class UC {
                #[Route('/users', name: 'i')]
                public function index() {}

                #[Route('/users/{id}', name: 's', methods: ['GET'])]
                public function show($id) {}

                #[Route('/users/{id}', name: 'u', methods: ['PUT'])]
                public function update($id) {}
            }
        """)
        rec = parse_controller(php)
        from datalift.symfony_lifter import SymfonyLiftResult
        text = render_urls(SymfonyLiftResult(controllers=[rec]))
        self.assertIn("path('users/', views.UC_index", text)
        self.assertIn("path('users/<int:id>/'", text)
        # GET + PUT on the same path should produce a dispatcher
        self.assertIn('def _dispatch_', text)
        self.assertIn('HttpResponseNotAllowed', text)


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_routes_and_controllers(self):
        from datalift.symfony_lifter import (
            SymfonyController, SymfonyLiftResult, SymfonyMethod, SymfonyRoute,
        )
        result = SymfonyLiftResult(
            controllers=[
                SymfonyController(
                    source=Path('UC.php'), class_name='UC',
                    methods=[SymfonyMethod(
                        name='index', visibility='public', args=[],
                        body_php='', body_django='',
                        routes=[SymfonyRoute(method='GET', path='/u',
                                              controller='UC', action='index')],
                    )],
                ),
            ],
            yaml_routes=[
                SymfonyRoute(method='GET', path='/y',
                              controller='YC', action='index', name='ya'),
            ],
        )
        text = render_worklist(result, 'app', Path('/tmp/app'))
        self.assertIn('liftsymfony worklist', text)
        self.assertIn('GET /u', text)
        self.assertIn('GET /y', text)
        self.assertIn('UC.php', text)
