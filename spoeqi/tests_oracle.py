"""Tests for spoeqi.oracle — data-flow only (no model load).

The deterministic LLM call is mocked. The external LLM call is
mocked or routed through a missing-provider branch. End-to-end
behavior with real models is covered by the manage.py smoke test.
"""

from unittest import mock

from django.test import TestCase

from spoeqi.models import Pact
from spoeqi import oracle


class AskOracleTest(TestCase):
    def setUp(self):
        self.pact = Pact.objects.create(name='oracle-test')

    @mock.patch('spoeqi.oracle.deterministic_generate')
    def test_echo_mode_returns_prompt_only(self, mocked_gen):
        mocked_gen.return_value = 'deterministic prompt body'
        result = oracle.ask_oracle(self.pact)
        self.assertEqual(result['prompt'], 'deterministic prompt body')
        self.assertIsNone(result['response'])
        self.assertIn('echo mode', result['error'])

    @mock.patch('spoeqi.oracle.deterministic_generate')
    def test_unknown_provider_returns_helpful_error(self, mocked_gen):
        mocked_gen.return_value = 'X'
        result = oracle.ask_oracle(self.pact, provider_name='no-such-provider')
        self.assertEqual(result['prompt'], 'X')
        self.assertIsNone(result['response'])
        self.assertIn('no-such-provider', result['error'])

    @mock.patch('spoeqi.oracle.deterministic_generate')
    def test_provider_call_succeeds(self, mocked_gen):
        mocked_gen.return_value = 'pact-derived question?'
        from identity.models import LLMProvider
        prov = LLMProvider.objects.create(
            name='unit-test-provider',
            base_url='http://localhost:9999/v1/chat/completions',
            model='fake-model',
        )
        fake_call = mock.MagicMock(return_value=('external answer', 12, 34, '', 250))
        with mock.patch('identity.llm_client.call_llm', fake_call):
            result = oracle.ask_oracle(self.pact, provider_name='unit-test-provider')
        self.assertEqual(result['prompt'], 'pact-derived question?')
        self.assertEqual(result['response'], 'external answer')
        self.assertEqual(result['tokens_in'], 12)
        self.assertEqual(result['tokens_out'], 34)
        self.assertEqual(result['latency_ms'], 250)
        self.assertIsNone(result['error'])
        # Confirm call_llm received our prompt.
        called_with = fake_call.call_args
        self.assertEqual(called_with.args[0], prov)
        self.assertEqual(called_with.args[1], 'pact-derived question?')

    @mock.patch('spoeqi.oracle.deterministic_generate')
    def test_provider_call_propagates_error(self, mocked_gen):
        mocked_gen.return_value = 'Q'
        from identity.models import LLMProvider
        LLMProvider.objects.create(
            name='broken-provider',
            base_url='http://does-not-resolve.example/v1/chat/completions',
            model='m',
        )
        fake_call = mock.MagicMock(return_value=(None, 0, 0, 'Network error: name resolution', 1500))
        with mock.patch('identity.llm_client.call_llm', fake_call):
            result = oracle.ask_oracle(self.pact, provider_name='broken-provider')
        self.assertIsNone(result['response'])
        self.assertIn('Network error', result['error'])
        self.assertEqual(result['latency_ms'], 1500)


class MakePromptTest(TestCase):
    @mock.patch('spoeqi.oracle.deterministic_generate')
    def test_threads_kwargs_through(self, mocked_gen):
        mocked_gen.return_value = 'p'
        pact = Pact.objects.create(name='kw-test')
        oracle.make_prompt(pact, component=7, generation=42, scale=0.05, rank=8,
                           max_new_tokens=80, model_name='gpt2',
                           target_weight='lm_head.weight')
        kwargs = mocked_gen.call_args.kwargs
        self.assertEqual(kwargs['component'], 7)
        self.assertEqual(kwargs['generation'], 42)
        self.assertEqual(kwargs['scale'], 0.05)
        self.assertEqual(kwargs['rank'], 8)
        self.assertEqual(kwargs['max_new_tokens'], 80)
        self.assertEqual(kwargs['model_name'], 'gpt2')
        self.assertEqual(kwargs['target_weight'], 'lm_head.weight')
