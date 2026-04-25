"""Tests for datalift.yii_lifter — Yii 2 → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.yii_lifter import (
    apply, parse_controller, parse_url_rules, parse_yii,
    render_urls, render_views, _camel_to_dashed,
)


class CamelDashTests(SimpleTestCase):

    def test_simple(self):
        self.assertEqual(_camel_to_dashed('Login'), 'login')

    def test_camel(self):
        self.assertEqual(_camel_to_dashed('LogOut'), 'log-out')

    def test_long(self):
        self.assertEqual(_camel_to_dashed('MyVeryLongAction'),
                          'my-very-long-action')


class ControllerParsingTests(SimpleTestCase):

    def test_basic_controller(self):
        php = dedent("""\
            <?php
            namespace app\\controllers;
            class SiteController extends Controller {
                public function actionIndex(): string {
                    return $this->render('index');
                }
                public function actionLogin() {
                    return $this->render('login');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIsNotNone(ctl)
        self.assertEqual(ctl.class_name, 'SiteController')
        self.assertEqual(ctl.controller_id, 'site')
        names = [a.name for a in ctl.actions]
        self.assertEqual(names, ['actionIndex', 'actionLogin'])
        self.assertEqual(ctl.actions[0].action_id, 'index')
        self.assertEqual(ctl.actions[1].action_id, 'login')

    def test_camel_action_id(self):
        php = dedent("""\
            <?php
            class SiteController extends Controller {
                public function actionLogOut() { }
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.actions[0].action_id, 'log-out')

    def test_action_with_args(self):
        php = dedent("""\
            <?php
            class PostController extends Controller {
                public function actionView($id) {
                    return $this->render('view');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.actions[0].args, ['id'])

    def test_render_translation(self):
        php = dedent("""\
            <?php
            class SiteController extends Controller {
                public function actionIndex(): string {
                    return $this->render('home');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("render(request, 'home.html')",
                      ctl.actions[0].body)

    def test_render_with_array(self):
        php = dedent("""\
            <?php
            class PostController extends Controller {
                public function actionView() {
                    return $this->render('view', ['post' => $post]);
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("render(request, 'view.html'", ctl.actions[0].body)

    def test_redirect_translation(self):
        php = dedent("""\
            <?php
            class SiteController extends Controller {
                public function actionLogout() {
                    return $this->goHome();
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertNotIn('return return', ctl.actions[0].body)
        self.assertIn("return redirect('/')", ctl.actions[0].body)

    def test_post_input(self):
        php = dedent("""\
            <?php
            class FooController extends Controller {
                public function actionBar() {
                    $email = Yii::$app->request->post('email');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("request.POST.get('email')", ctl.actions[0].body)

    def test_session_get(self):
        php = dedent("""\
            <?php
            class FooController extends Controller {
                public function actionBar() {
                    $name = Yii::$app->session->get('name');
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("request.session.get('name')", ctl.actions[0].body)

    def test_user_isguest(self):
        php = dedent("""\
            <?php
            class FooController extends Controller {
                public function actionBar() {
                    if (Yii::$app->user->isGuest) { return $this->goHome(); }
                }
            }
        """)
        ctl = parse_controller(php)
        self.assertIn("not request.user.is_authenticated",
                      ctl.actions[0].body)

    def test_verb_filter_extracted(self):
        php = dedent("""\
            <?php
            class SiteController extends Controller {
                public function behaviors(): array {
                    return [
                        'verbs' => [
                            'class' => VerbFilter::class,
                            'actions' => [
                                'logout' => ['post'],
                                'delete' => ['post', 'delete'],
                            ],
                        ],
                    ];
                }
                public function actionIndex() {}
                public function actionLogout() {}
                public function actionDelete() {}
            }
        """)
        ctl = parse_controller(php)
        self.assertEqual(ctl.verb_map.get('logout'), ['POST'])
        self.assertEqual(sorted(ctl.verb_map.get('delete') or []),
                          ['DELETE', 'POST'])

    def test_non_action_methods_ignored(self):
        php = dedent("""\
            <?php
            class SiteController extends Controller {
                public function behaviors(): array { return []; }
                public function beforeAction($action) { return true; }
                public function actionIndex() {}
            }
        """)
        ctl = parse_controller(php)
        names = [a.name for a in ctl.actions]
        self.assertEqual(names, ['actionIndex'])

    def test_non_controller_skipped(self):
        php = "<?php class JustAClass {}"
        self.assertIsNone(parse_controller(php))


class URLRuleTests(SimpleTestCase):

    def test_extract_rules(self):
        php = dedent("""\
            <?php
            return [
                'components' => [
                    'urlManager' => [
                        'enablePrettyUrl' => true,
                        'rules' => [
                            'posts/<id:\\d+>' => 'post/view',
                            'posts' => 'post/index',
                        ],
                    ],
                ],
            ];
        """)
        rules = parse_url_rules(php)
        # Should pull both rules
        self.assertEqual(len(rules), 2)
        pats = {p for p, _ in rules}
        self.assertIn('posts', pats)


class FileWalkerTests(SimpleTestCase):

    def test_parse_basic_app(self):
        tmp = Path(tempfile.mkdtemp()) / 'app'
        (tmp / 'controllers').mkdir(parents=True)
        (tmp / 'controllers' / 'SiteController.php').write_text(dedent("""\
            <?php
            namespace app\\controllers;
            class SiteController extends Controller {
                public function actionIndex(): string {
                    return $this->render('index');
                }
                public function actionAbout() {
                    return $this->render('about');
                }
            }
        """))
        result = parse_yii(tmp)
        self.assertEqual(len(result.controllers), 1)
        # Routes: site/index/, site/about/, plus /site/ → actionIndex
        paths = sorted(r.path for r in result.routes)
        self.assertIn('site/index/', paths)
        self.assertIn('site/about/', paths)
        self.assertIn('site/', paths)


class RenderingTests(SimpleTestCase):

    def test_render_urls_basic(self):
        from datalift.yii_lifter import YiiLiftResult, YiiRoute
        result = YiiLiftResult(routes=[
            YiiRoute(http_method='ANY', path='site/index/',
                     controller='SiteController', action='actionIndex'),
        ])
        text = render_urls(result, 'app')
        self.assertIn(
            "path('site/index/', views.SiteController_actionIndex)",
            text,
        )

    def test_render_views_emits_function(self):
        from datalift.yii_lifter import (
            YiiLiftResult, YiiController, YiiAction,
        )
        result = YiiLiftResult(controllers=[
            YiiController(source=Path('SiteController.php'),
                           class_name='SiteController',
                           controller_id='site',
                           actions=[YiiAction(
                               name='actionIndex', action_id='index', args=[],
                               body="return HttpResponse('hi')", raw_body='')],
                           )
        ])
        text = render_views(result)
        self.assertIn('def SiteController_actionIndex(request):', text)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_outputs(self):
        from datalift.yii_lifter import (
            YiiLiftResult, YiiController, YiiAction, YiiRoute,
        )
        tmp = Path(tempfile.mkdtemp()); proj = tmp / 'proj'; proj.mkdir()
        result = YiiLiftResult(
            routes=[YiiRoute(http_method='ANY', path='site/index/',
                              controller='SiteController',
                              action='actionIndex')],
            controllers=[YiiController(
                source=Path('SiteController.php'),
                class_name='SiteController', controller_id='site',
                actions=[YiiAction(name='actionIndex', action_id='index',
                                    args=[],
                                    body="return HttpResponse('ok')",
                                    raw_body='')]
            )],
        )
        apply(result, proj, 'myapp')
        urls = (proj / 'myapp' / 'urls_yii.py').read_text()
        views = (proj / 'myapp' / 'views_yii.py').read_text()
        self.assertIn(
            "path('site/index/', views.SiteController_actionIndex)", urls)
        self.assertIn('def SiteController_actionIndex(request):', views)
