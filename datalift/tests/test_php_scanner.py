"""Tests for datalift.php_scanner.

The PHP scanner is used by `liftphp` to flag secrets / PII before a
legacy PHP tree is handed to an assistant for porting advice. These
tests pin down what each detector matches (and doesn't).

Run via:
    venv/bin/python manage.py test datalift.tests.test_php_scanner
"""

from django.test import SimpleTestCase

from datalift.php_scanner import Finding, redact, scan


class ScanReturnsListOfFindings(SimpleTestCase):
    def test_clean_file_returns_empty(self):
        self.assertEqual(scan('<?php echo "hello"; ?>'), [])

    def test_returns_finding_instances(self):
        src = "<?php $db = mysql_connect('localhost', 'root', 'hunter2'); ?>"
        findings = scan(src)
        self.assertTrue(all(isinstance(f, Finding) for f in findings))


class DbConnectDetection(SimpleTestCase):
    """db-credentials fires when a DB-connect call carries a literal
    password argument."""

    def test_mysql_connect_with_literal_password(self):
        src = """<?php mysql_connect('localhost', 'root', 'hunter2'); ?>"""
        cats = {f.category for f in scan(src)}
        self.assertIn('db-credentials', cats)

    def test_mysqli_connect_with_literal_password(self):
        src = """<?php mysqli_connect('db.example.com', 'app', 'sekret'); ?>"""
        cats = {f.category for f in scan(src)}
        self.assertIn('db-credentials', cats)

    def test_connect_with_variable_password_is_not_flagged_as_credentials(self):
        # When the password comes from a variable we flag it under
        # password-var / password-const instead of db-credentials.
        src = "<?php mysql_connect('localhost', 'root', $pw); ?>"
        cats = {f.category for f in scan(src)}
        self.assertNotIn('db-credentials', cats)


class PasswordAssignmentDetection(SimpleTestCase):
    """The password-const / password-var family. The variable-name
    regex deliberately requires a prefix-then-keyword shape so a
    bare `$password` doesn't blow up every simple PHP file — you
    need something like `$db_password` / `$user_secret`."""

    def test_password_const(self):
        src = "<?php define('DB_PASSWORD', 'correct horse battery'); ?>"
        cats = {f.category for f in scan(src)}
        self.assertIn('password-const', cats)

    def test_password_var_with_prefix(self):
        src = "<?php $db_password = 'abc123'; ?>"
        cats = {f.category for f in scan(src)}
        self.assertIn('password-var', cats)

    def test_password_var_also_fires_on_api_key_token_secret(self):
        # The scanner flags the broader family — not just literal
        # "password" but tokens and secrets by name. Each needs a
        # `prefix_` for the regex to bite.
        for name in ('my_api_key', 'user_token', 'shared_secret',
                      'app_apiKey'):
            src = f"<?php ${name} = 'XXXXXXXXXXXXXXXX'; ?>"
            cats = {f.category for f in scan(src)}
            self.assertIn('password-var', cats, msg=f'missed ${name}')

    def test_bare_password_variable_is_deliberately_not_flagged(self):
        # `$password` with no prefix is the scanner's documented
        # false-positive reduction — commit a test so nobody
        # "fixes" this by mistake.
        src = "<?php $password = 'hunter2'; ?>"
        findings = [f for f in scan(src) if f.category == 'password-var']
        self.assertEqual(findings, [])


class BasicAuthUrlDetection(SimpleTestCase):
    def test_http_with_credentials(self):
        src = "<?php $url = 'https://user:s3cret@example.com/api'; ?>"
        cats = {f.category for f in scan(src)}
        self.assertIn('basic-auth-url', cats)


class PrivateKeyDetection(SimpleTestCase):
    def test_rsa_private_key_header(self):
        src = (
            '<?php $k = "-----BEGIN RSA PRIVATE KEY-----\n'
            'MIIEpAIBAAKCAQEA…\n-----END RSA PRIVATE KEY-----"; ?>'
        )
        cats = {f.category for f in scan(src)}
        self.assertIn('private-key-block', cats)

    def test_ec_private_key_header(self):
        src = (
            '<?php $k = "-----BEGIN EC PRIVATE KEY-----\n…\n'
            '-----END EC PRIVATE KEY-----"; ?>'
        )
        cats = {f.category for f in scan(src)}
        self.assertIn('private-key-block', cats)


class EmailPiiDetection(SimpleTestCase):
    def test_email_literal_in_source(self):
        # The MediaWiki regression — copyright notices with
        # emails get flagged as medium. Use a real-looking domain
        # (not example.com / test.com, which are explicitly
        # excluded as placeholder domains).
        src = "<?php // Copyright (C) 2007 Roan <roan@wikimedia.org> ?>"
        findings = scan(src)
        self.assertTrue(
            any(f.category == 'email-pii' for f in findings),
            msg='scanner missed the inline email literal',
        )

    def test_placeholder_domains_are_not_flagged(self):
        # example.com / test.com / localhost etc. are explicitly
        # excluded — they're not real PII.
        for domain in ('example.com', 'test.com', 'foo.com', 'localhost'):
            src = f"<?php // contact: alice@{domain} ?>"
            findings = [f for f in scan(src) if f.category == 'email-pii']
            self.assertEqual(
                findings, [],
                msg=f'{domain} shouldnt be flagged (placeholder)',
            )


class InlineSqlInsertDetection(SimpleTestCase):
    def test_flagged_insert_with_literal_values(self):
        # Fixture-style INSERTs embedded in PHP are often seed
        # data the scanner wants a human to review.
        src = """<?php
        $db->query("INSERT INTO users (email, name) VALUES
                    ('a@x.com', 'alice')");
        ?>"""
        cats = {f.category for f in scan(src)}
        self.assertIn('inline-sql-insert', cats)


class MaskingBehaviour(SimpleTestCase):
    def test_snippet_does_not_contain_raw_password(self):
        # Core privacy invariant: the snippet shown in the
        # worklist has the secret masked to mask characters.
        src = "<?php $db_password = 'hunter2-superlong-secret'; ?>"
        findings = scan(src)
        pw_findings = [f for f in findings if f.category == 'password-var']
        self.assertTrue(pw_findings)
        for f in pw_findings:
            self.assertNotIn(
                'hunter2-superlong-secret',
                f.snippet,
                msg='snippet leaked raw password material',
            )


class RedactProducesCleanOutput(SimpleTestCase):
    def test_redact_replaces_each_finding(self):
        # Passwords from password-var findings get replaced with a
        # category-named placeholder.
        src = "<?php $db_password = 'hunter2superlongsecret'; ?>"
        findings = scan(src)
        redacted = redact(src, findings)
        self.assertNotIn('hunter2superlongsecret', redacted)
        self.assertIn('REDACTED', redacted)

    def test_redact_idempotent_on_no_findings(self):
        src = '<?php echo "hello"; ?>'
        self.assertEqual(redact(src, []), src)


class SeverityAssignment(SimpleTestCase):
    """The scanner's three severity levels — critical / high /
    medium — map to how urgently a reviewer should care."""

    def test_db_credentials_is_critical(self):
        src = "<?php mysql_connect('localhost', 'root', 'hunter2'); ?>"
        findings = [f for f in scan(src) if f.category == 'db-credentials']
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, 'critical')

    def test_password_var_is_high(self):
        src = "<?php $db_password = 'hunter2'; ?>"
        findings = [f for f in scan(src) if f.category == 'password-var']
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, 'high')

    def test_email_pii_is_medium(self):
        src = "<?php // author@wikimedia.org ?>"
        findings = [f for f in scan(src) if f.category == 'email-pii']
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, 'medium')


class LineNumbersAreAccurate(SimpleTestCase):
    def test_line_number_reported_correctly(self):
        # Put the finding on a known line.
        src = "<?php\n// filler\n$db_password = 'hunter2';\n?>"
        findings = scan(src)
        self.assertTrue(findings)
        self.assertEqual(findings[0].line, 3)
