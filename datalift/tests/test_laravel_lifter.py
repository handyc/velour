"""Tests for datalift.laravel_lifter — Laravel routes + controllers → Django.

The first PHP business-logic translator. These tests pin every
conventional Laravel idiom we recognise, so future generalisations
can't regress."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.laravel_lifter import (
    apply,
    laravel_path_to_django,
    parse_controller,
    parse_laravel,
    parse_routes,
    render_urls,
    render_views,
    render_worklist,
    translate_method_body,
)


class PathTranslationTests(SimpleTestCase):

    def test_static_path(self):
        self.assertEqual(laravel_path_to_django('/users'), 'users/')

    def test_root_path(self):
        self.assertEqual(laravel_path_to_django('/'), '')

    def test_int_param_id(self):
        self.assertEqual(laravel_path_to_django('/users/{id}'),
                         'users/<int:id>/')

    def test_int_param_user_id(self):
        self.assertEqual(laravel_path_to_django('/posts/{post_id}/comments'),
                         'posts/<int:post_id>/comments/')

    def test_slug_param(self):
        self.assertEqual(laravel_path_to_django('/posts/{slug}'),
                         'posts/<slug:slug>/')

    def test_str_fallback(self):
        # Unknown param name → str.
        self.assertEqual(laravel_path_to_django('/blog/{foo}'),
                         'blog/<str:foo>/')


class RouteParsingTests(SimpleTestCase):

    def test_bracket_form(self):
        php = "Route::get('/users', [UserController::class, 'index']);"
        routes, _ = parse_routes(php)
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r.method, 'get')
        self.assertEqual(r.path, '/users')
        self.assertEqual(r.controller, 'UserController')
        self.assertEqual(r.action, 'index')

    def test_at_form(self):
        php = "Route::post('/users', 'UserController@store');"
        routes, _ = parse_routes(php)
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r.method, 'post')
        self.assertEqual(r.controller, 'UserController')
        self.assertEqual(r.action, 'store')

    def test_route_with_name(self):
        php = ("Route::get('/users', [UserController::class, 'index'])"
               "->name('users.index');")
        routes, _ = parse_routes(php)
        self.assertEqual(routes[0].name, 'users.index')

    def test_route_with_middleware(self):
        php = ("Route::get('/dash', [HomeController::class, 'dash'])"
               "->middleware('auth');")
        routes, _ = parse_routes(php)
        self.assertEqual(routes[0].middleware, ['auth'])

    def test_route_resource_expands(self):
        php = "Route::resource('posts', PostController::class);"
        routes, _ = parse_routes(php)
        # Should expand to 7 conventional REST routes.
        self.assertEqual(len(routes), 7)
        actions = sorted(r.action for r in routes)
        self.assertEqual(actions, [
            'create', 'destroy', 'edit', 'index', 'show', 'store', 'update',
        ])

    def test_api_resource_expands_to_five(self):
        php = "Route::apiResource('items', ItemController::class);"
        routes, _ = parse_routes(php)
        self.assertEqual(len(routes), 5)
        # No create / edit (those are HTML-only routes).
        actions = sorted(r.action for r in routes)
        self.assertEqual(actions, [
            'destroy', 'index', 'show', 'store', 'update',
        ])

    def test_route_view_emits_view_only(self):
        php = "Route::view('/about', 'pages.about');"
        routes, _ = parse_routes(php)
        self.assertEqual(routes[0].action, '_view_only')

    def test_unknown_route_form_flagged(self):
        php = "Route::macro('thing', function() { return 'x'; });"
        _, skipped = parse_routes(php)
        self.assertEqual(len(skipped), 1)


class UrlsRenderingTests(SimpleTestCase):

    def test_renders_urlpatterns(self):
        from datalift.laravel_lifter import RouteRecord
        routes = [
            RouteRecord(method='get', path='/users',
                        controller='UserController', action='index',
                        name='users.index'),
        ]
        text = render_urls(routes, 'app')
        self.assertIn('urlpatterns = [', text)
        self.assertIn("path('users/', views.UserController_index", text)
        self.assertIn("name='users.index'", text)


class BodyTranslationTests(SimpleTestCase):

    def test_view_call(self):
        php = "return view('users.index', ['users' => $users]);"
        out, _ = translate_method_body(php)
        self.assertIn("render(request, 'users/index.html'", out)

    def test_eloquent_all(self):
        php = "$users = User::all();"
        out, _ = translate_method_body(php)
        self.assertIn('users = User.objects.all()', out)

    def test_eloquent_findorfail(self):
        php = "$user = User::findOrFail($id);"
        out, _ = translate_method_body(php)
        self.assertIn('user = get_object_or_404(User, id=id)', out)

    def test_eloquent_find(self):
        php = "$post = Post::find($id);"
        out, _ = translate_method_body(php)
        self.assertIn('Post.objects.filter(id=id).first()', out)

    def test_redirect_route(self):
        php = "return redirect()->route('users.index');"
        out, _ = translate_method_body(php)
        self.assertIn("redirect('users.index')", out)

    def test_this_view_make(self):
        """Pterodactyl-style $this->view->make() — translates same
        as the global view() helper."""
        php = "return $this->view->make('admin.api.index', ['keys' => $keys]);"
        out, _ = translate_method_body(php)
        self.assertIn("render(request, 'admin/api/index.html'", out)

    def test_redirect_path(self):
        php = "return redirect('/login');"
        out, _ = translate_method_body(php)
        self.assertIn("redirect('/login')", out)

    def test_response_json(self):
        php = "return response()->json($data);"
        out, _ = translate_method_body(php)
        self.assertIn('JsonResponse(data)', out)

    def test_auth_user(self):
        php = "$user = Auth::user();"
        out, _ = translate_method_body(php)
        self.assertIn('user = request.user', out)

    def test_auth_check(self):
        php = "if (Auth::check()) { ... }"
        out, _ = translate_method_body(php)
        self.assertIn('request.user.is_authenticated', out)

    def test_request_input(self):
        php = "$name = request()->input('name');"
        out, _ = translate_method_body(php)
        self.assertIn('request.POST.get', out)

    def test_dollar_var_strip(self):
        php = "$x = 5; $y = $x + 1;"
        out, _ = translate_method_body(php)
        self.assertIn('x = 5', out)
        self.assertIn('y = x + 1', out)

    def test_save_method(self):
        php = "$user->save();"
        out, _ = translate_method_body(php)
        self.assertIn('user.save()', out)

    def test_fat_arrow_to_colon(self):
        # `=>` becomes `:` (with spaces preserved from source).
        php = "$arr = ['key' => 'value'];"
        out, _ = translate_method_body(php)
        # Whitespace around the colon may vary; just confirm the
        # operator was converted.
        self.assertNotIn('=>', out)
        self.assertIn("'key'", out)
        self.assertIn("'value'", out)

    def test_db_facade_flagged(self):
        php = "DB::table('users')->get();"
        out, skipped = translate_method_body(php)
        self.assertTrue(any('DB::' in s for s in skipped))
        self.assertIn('LARAVEL-LIFT', out)

    def test_eloquent_where_translated_not_flagged(self):
        """As of the chain-translator round, simple where() chains are
        translated rather than flagged."""
        php = "$users = User::where('active', true)->get();"
        out, skipped = translate_method_body(php)
        self.assertIn("User.objects.filter(active=True)", out)
        self.assertEqual(skipped, [])


class EloquentChainTests(SimpleTestCase):
    """Eloquent query-builder chain translation. The biggest source of
    porter markers in the first Pterodactyl run was untranslated chains;
    these tests pin every chain shape we now translate cleanly."""

    def test_simple_where_two_args(self):
        php = "User::where('email', $email)->first();"
        out, _ = translate_method_body(php)
        self.assertIn("User.objects.filter(email=email).first()", out)

    def test_where_with_op(self):
        php = "User::where('age', '>', 18)->get();"
        out, _ = translate_method_body(php)
        self.assertIn("User.objects.filter(age__gt=18)", out)

    def test_where_lt_op(self):
        php = "User::where('age', '<', 65)->get();"
        out, _ = translate_method_body(php)
        self.assertIn("age__lt=65", out)

    def test_where_gte_lte(self):
        php = "User::where('a', '>=', 1)->where('b', '<=', 10)->get();"
        out, _ = translate_method_body(php)
        self.assertIn("a__gte=1", out)
        self.assertIn("b__lte=10", out)

    def test_where_neq_becomes_exclude(self):
        php = "User::where('status', '!=', 'banned')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("exclude(status='banned')", out)

    def test_where_like_to_icontains(self):
        php = "User::where('name', 'like', $q)->get();"
        out, _ = translate_method_body(php)
        self.assertIn("name__icontains=q", out)

    def test_where_null(self):
        php = "User::whereNull('deleted_at')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("deleted_at__isnull=True", out)

    def test_where_not_null(self):
        php = "User::whereNotNull('verified_at')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("verified_at__isnull=False", out)

    def test_where_in(self):
        php = "User::whereIn('id', [1, 2, 3])->get();"
        out, _ = translate_method_body(php)
        self.assertIn("id__in=", out)

    def test_order_by(self):
        php = "User::orderBy('name')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("order_by('name')", out)

    def test_order_by_desc(self):
        php = "User::orderBy('created_at', 'desc')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("order_by('-created_at')", out)

    def test_latest(self):
        php = "User::latest()->first();"
        out, _ = translate_method_body(php)
        self.assertIn("order_by('-created_at')", out)
        self.assertIn(".first()", out)

    def test_oldest_with_column(self):
        php = "User::oldest('updated_at')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("order_by('updated_at')", out)

    def test_pluck(self):
        php = "User::pluck('email')->all();"
        out, _ = translate_method_body(php)
        self.assertIn("values_list('email', flat=True)", out)

    def test_select(self):
        php = "User::select('id', 'name')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("values('id', 'name')", out)

    def test_distinct(self):
        php = "User::distinct()->get();"
        out, _ = translate_method_body(php)
        self.assertIn(".distinct()", out)

    def test_with_eager_load(self):
        php = "User::with('posts', 'comments')->get();"
        out, _ = translate_method_body(php)
        self.assertIn("select_related('posts', 'comments')", out)

    def test_full_chain(self):
        php = ("$users = User::where('active', true)"
               "->whereNull('deleted_at')"
               "->orderBy('name')"
               "->limit(10)"
               "->get();")
        out, _ = translate_method_body(php)
        # We translate active=True, deleted_at__isnull=True, order_by('name'),
        # then [:10] terminal.
        self.assertIn("User.objects", out)
        self.assertIn("filter(active=True)", out)
        self.assertIn("deleted_at__isnull=True", out)
        self.assertIn("order_by('name')", out)
        self.assertIn("[:10]", out)


class ControllerParsingTests(SimpleTestCase):

    def test_simple_controller(self):
        php = dedent("""\
            <?php
            namespace App\\Http\\Controllers;
            use App\\Models\\User;

            class UserController extends Controller {
                public function index() {
                    $users = User::all();
                    return view('users.index', ['users' => $users]);
                }
                public function show($id) {
                    $user = User::findOrFail($id);
                    return view('users.show', ['user' => $user]);
                }
            }
        """)
        rec = parse_controller(php)
        self.assertEqual(rec.class_name, 'UserController')
        self.assertEqual(rec.base_class, 'Controller')
        self.assertEqual(len(rec.methods), 2)
        names = sorted(m.name for m in rec.methods)
        self.assertEqual(names, ['index', 'show'])

        index = next(m for m in rec.methods if m.name == 'index')
        self.assertIn('User.objects.all()', index.body_django)
        self.assertIn("'users/index.html'", index.body_django)

    def test_controller_with_typed_args(self):
        php = dedent("""\
            <?php
            class PostController {
                public function show(int $id): Response {
                    return view('posts.show', ['id' => $id]);
                }
            }
        """)
        rec = parse_controller(php)
        self.assertEqual(rec.methods[0].name, 'show')
        self.assertEqual(rec.methods[0].args, ['int $id'])

    def test_controller_with_request_arg(self):
        php = dedent("""\
            <?php
            class PostController {
                public function store(Request $request) {
                    return redirect()->route('posts.index');
                }
            }
        """)
        rec = parse_controller(php)
        # `Request $request` is dropped — Django gets request automatically.
        from datalift.laravel_lifter import _php_args_to_python
        py_args = _php_args_to_python(rec.methods[0].args)
        self.assertEqual(py_args, ['request'])


class ViewsRenderingTests(SimpleTestCase):

    def test_renders_function_views(self):
        php = dedent("""\
            <?php
            class UserController {
                public function index() {
                    $users = User::all();
                    return view('users.index', ['users' => $users]);
                }
            }
        """)
        rec = parse_controller(php)
        text = render_views([rec])
        self.assertIn('def UserController_index(request):', text)
        self.assertIn('User.objects.all()', text)

    def test_skips_non_public_methods(self):
        php = dedent("""\
            <?php
            class UserController {
                public function index() { return view('users.index'); }
                private function helper() { return 1; }
            }
        """)
        rec = parse_controller(php)
        text = render_views([rec])
        self.assertIn('UserController_index', text)
        self.assertNotIn('UserController_helper', text)


class WalkerTests(SimpleTestCase):

    def test_parse_laravel_finds_routes_and_controllers(self):
        tmp = Path(tempfile.mkdtemp())
        app = tmp / 'laravel'
        (app / 'routes').mkdir(parents=True)
        (app / 'routes' / 'web.php').write_text(dedent("""\
            <?php
            Route::get('/', [HomeController::class, 'index']);
            Route::resource('users', UserController::class);
        """))
        (app / 'app' / 'Http' / 'Controllers').mkdir(parents=True)
        (app / 'app' / 'Http' / 'Controllers' / 'HomeController.php').write_text(dedent("""\
            <?php
            class HomeController {
                public function index() {
                    return view('home');
                }
            }
        """))
        result = parse_laravel(app)
        # 1 (home) + 7 (resource expansion) = 8 routes
        self.assertEqual(len(result.routes), 8)
        self.assertEqual(len(result.controllers), 1)
        self.assertEqual(result.controllers[0].class_name, 'HomeController')

    def test_apply_writes_urls_and_views(self):
        tmp = Path(tempfile.mkdtemp())
        app = tmp / 'laravel'
        (app / 'routes').mkdir(parents=True)
        (app / 'routes' / 'web.php').write_text(
            "<?php Route::get('/u', [UserController::class, 'index']);"
        )
        (app / 'app' / 'Http' / 'Controllers').mkdir(parents=True)
        (app / 'app' / 'Http' / 'Controllers' / 'UserController.php').write_text(
            dedent("""\
            <?php
            class UserController {
                public function index() {
                    return view('u.index');
                }
            }
            """)
        )
        proj = tmp / 'proj'
        proj.mkdir()
        result = parse_laravel(app)
        log = apply(result, proj, 'myapp')
        urls_text = (proj / 'myapp' / 'urls_laravel.py').read_text()
        views_text = (proj / 'myapp' / 'views_laravel.py').read_text()
        self.assertIn("path('u/', views.UserController_index", urls_text)
        self.assertIn('def UserController_index(request):', views_text)
        self.assertIn("render(request, 'u/index.html'", views_text)


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_routes_and_controllers(self):
        from datalift.laravel_lifter import (
            ControllerMethod, ControllerRecord, LiftResult, RouteRecord,
        )
        result = LiftResult(
            routes=[
                RouteRecord(method='get', path='/u',
                            controller='UC', action='index',
                            name='u.index', middleware=['auth']),
            ],
            controllers=[
                ControllerRecord(
                    source=Path('UC.php'), class_name='UC',
                    methods=[ControllerMethod(
                        name='index', visibility='public', args=[],
                        body_php='', body_django='', skipped=['DB:: facade'],
                    )],
                    skipped=['DB:: facade'],
                ),
            ],
            skipped_routes=['Route::macro(...)'],
        )
        text = render_worklist(result, 'app', Path('/tmp/app'))
        self.assertIn('liftlaravel worklist', text)
        self.assertIn('GET /u', text)
        self.assertIn('UC@index', text)
        self.assertIn('middleware: auth', text)
        self.assertIn('UC.php', text)
        self.assertIn('Route::macro', text)
        self.assertIn('DB:: facade', text)


class RealisticControllerTests(SimpleTestCase):
    """A realistic Laravel controller exercising many idioms at once."""

    SAMPLE = dedent("""\
        <?php
        namespace App\\Http\\Controllers;
        use App\\Models\\Post;
        use Illuminate\\Http\\Request;

        class PostController extends Controller {
            public function index() {
                $posts = Post::all();
                return view('posts.index', ['posts' => $posts]);
            }

            public function show($id) {
                $post = Post::findOrFail($id);
                return view('posts.show', ['post' => $post]);
            }

            public function store(Request $request) {
                $title = request()->input('title');
                $body = request()->input('body');
                $post = Post::create(['title' => $title, 'body' => $body]);
                return redirect()->route('posts.show', ['id' => $post->id]);
            }

            public function destroy($id) {
                $post = Post::findOrFail($id);
                $post->delete();
                return redirect('/posts');
            }
        }
    """)

    def test_full_controller_translation(self):
        rec = parse_controller(self.SAMPLE)
        self.assertEqual(rec.class_name, 'PostController')
        self.assertEqual(len(rec.methods), 4)
        names = sorted(m.name for m in rec.methods)
        self.assertEqual(names, ['destroy', 'index', 'show', 'store'])

        # Spot-check the index method's translation.
        index = next(m for m in rec.methods if m.name == 'index')
        self.assertIn('Post.objects.all()', index.body_django)
        self.assertIn("'posts/index.html'", index.body_django)

        show = next(m for m in rec.methods if m.name == 'show')
        self.assertIn('get_object_or_404(Post, id=id)', show.body_django)

        destroy = next(m for m in rec.methods if m.name == 'destroy')
        self.assertIn('post.delete()', destroy.body_django)
        self.assertIn("redirect('/posts')", destroy.body_django)

        store = next(m for m in rec.methods if m.name == 'store')
        self.assertIn('Post.objects.create', store.body_django)
        self.assertIn("redirect('posts.show'", store.body_django)
