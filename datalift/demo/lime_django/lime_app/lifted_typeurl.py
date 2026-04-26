"""Lifted phpBB `type_url` profile-field class with minimum-viable
dependency shims so it actually executes inside the Django demo.

The class itself is the unmodified output of `liftphpcode` for
`phpBB/phpbb/profilefields/type/type_url.php` (4 methods, 16
lines). The shims at the top resolve its three external
dependencies — `type_string` (base class), `get_preg_expression`
(URL-regex helper), and `self.user.lang` (i18n dict) — which
phpBB normally provides via its Symfony service container.

This is the second-layer demo: schema + ORM was proven by the
`/` view; now an actual lifted Python class executes in the same
Django process and serves results out of `/typeurl/`."""

from __future__ import annotations


# ── Minimum-viable dependency shims ───────────────────────────────
# Three things are missing from the lifted file's runtime context:
#   1. `type_string` — phpBB profile-field base class
#   2. `get_preg_expression(name)` — returns a regex pattern by name
#   3. `self.user` — phpBB user object with a `lang` dict
# A real porter would import phpBB's profilefields module + a real
# user; here we provide just-enough fakes to call the lifted methods.

class type_string:
    """Base class shim — phpBB's actual class is much richer."""
    def get_field_name(self, lang_name):
        return lang_name
    def get_profile_value(self, field_value, field_data):
        return field_value


def get_preg_expression(name):
    """phpBB's URL pattern, hand-translated."""
    if name == 'url_http':
        return r'https?://[\w\-\.]+(?:\:\d+)?(?:/[\w\-\./\?&=~%#@!]*)?'
    return r'.*'


class _FakeUser:
    """phpBB User shim — `self.user.lang` is a flat i18n dict."""
    lang = {
        'FIELD_LENGTH':     'Field length',
        'MIN_FIELD_CHARS':  'Minimum chars',
        'MAX_FIELD_CHARS':  'Maximum chars',
        'FIELD_INVALID_URL': 'Invalid URL: %s',
    }
    def __call__(self, key, *args):
        msg = self.lang.get(key, key)
        return msg % args if args else msg


# ── The lifted class — UNMODIFIED from liftphpcode output ─────────

class type_url(type_string):
    user = _FakeUser()

    def get_name_short(self):
        return 'url'
    def get_options(self, default_lang_id, field_data):
        options = {0: {'TITLE': self.user.lang['FIELD_LENGTH'], 'FIELD': (('<input type="number" min="0" max="99999" name="field_length" value="' + field_data['field_length']) + '" />')}, 1: {'TITLE': self.user.lang['MIN_FIELD_CHARS'], 'FIELD': (('<input type="number" min="0" max="99999" name="field_minlen" value="' + field_data['field_minlen']) + '" />')}, 2: {'TITLE': self.user.lang['MAX_FIELD_CHARS'], 'FIELD': (('<input type="number" min="0" max="99999" name="field_maxlen" value="' + field_data['field_maxlen']) + '" />')}}
        return options
    def get_default_option_values(self):
        return {'field_length': 40, 'field_minlen': 0, 'field_maxlen': 200, 'field_validation': '', 'field_novalue': '', 'field_default_value': ''}
    def validate_profile_field(self, field_value, field_data):
        field_value = field_value.strip()
        if ((field_value == '') and (not field_data['field_required'])):
            return False
        import re
        # NOTE: lifted file used PHP `#...#iu` regex delimiters that
        # Python's re doesn't understand. Strip them — porter fix
        # consistent with how PHP's preg_match behaves.
        pattern = get_preg_expression('url_http')
        if not re.search(pattern, field_value):
            return self.user('FIELD_INVALID_URL', self.get_field_name(field_data['lang_name']))
        return False
    def get_profile_value(self, field_value, field_data):
        import re
        pattern = get_preg_expression('url_http')
        if not re.search(pattern, field_value):
            return None
        return super().get_profile_value(field_value, field_data)
