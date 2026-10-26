import copy
import unittest

from tools.trace_xnu_c_boot import crypto_registration_contract


class CryptoBootEvidenceTests(unittest.TestCase):
    def events(self):
        return [dict(function="_register_crypto_functions", table_pointer=0x12340000),
                dict(function="_register_and_init_prng"),
                dict(function="_kmem_crypto_init", crypto_functions_pointer=0x12340000,
                     kernel_prng_ready=True)]

    def test_ordered_original_registrations_and_hook_return_are_scoped_evidence(self):
        result = crypto_registration_contract(self.events(), 0x12340000, True)
        self.assertTrue(result["registration_contract_passed"])
        self.assertFalse(result["complete_crypto_provider"])
        self.assertFalse(result["boot_approved"])

    def test_return_without_original_registration_is_not_accepted(self):
        for events in ([], self.events()[1:], self.events()[::2], self.events()[:2]):
            self.assertFalse(crypto_registration_contract(events, 0x12340000, True)["registration_contract_passed"])

    def test_wrong_order_duplicate_registration_and_late_ready_are_rejected(self):
        ordered = self.events()
        cases = [list(reversed(ordered)), [ordered[1], ordered[0], ordered[2]], ordered + [ordered[0]]]
        late_ready = copy.deepcopy(ordered)
        late_ready[-1]["kernel_prng_ready"] = False
        cases.append(late_ready)
        mismatched_table = copy.deepcopy(ordered)
        mismatched_table[-1]["crypto_functions_pointer"] = 0x56780000
        cases.append(mismatched_table)
        for events in cases:
            self.assertFalse(crypto_registration_contract(events, 0x12340000, True)["registration_contract_passed"])

    def test_null_or_changed_provider_and_unready_prng_are_rejected(self):
        for pointer, ready in ((0, True), (0x56780000, True), (0x12340000, False)):
            self.assertFalse(crypto_registration_contract(self.events(), pointer, ready)["registration_contract_passed"])


if __name__ == "__main__":
    unittest.main()
