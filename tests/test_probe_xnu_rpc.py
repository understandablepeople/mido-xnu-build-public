from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.probe_xnu_rpc import inspect_object, object_command, probe


class RpcBuildProbeTests(unittest.TestCase):
    def test_only_one_object_is_requested_with_real_werror_and_no_lto(self):
        command = object_command(Path('/source'), Path('/build'), Path('/generated'), 'iphoneos', '/availability.pl')
        self.assertEqual(command[-1], 'OSObject.iig.cpo')
        self.assertIn('BUILD_LTO=0', command)
        self.assertNotIn('BUILD_WERROR=0', command)
        self.assertNotIn('build', command)
        self.assertIn(str(Path('/generated/Makefile')), command)

    def test_bitcode_executable_and_nonbaseline_objects_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'object.cpo'
            for data in (b'BC\xc0\xde' + bytes(28),
                         struct.pack('<8I', 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0),
                         struct.pack('<8I', 0xFEEDFACF, 0x0100000C, 2, 1, 0, 0, 0, 0)):
                path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'ARM64 Mach-O object'):
                    inspect_object(path)
            path.write_bytes(struct.pack('<8I', 0xFEEDFACF, 0x0100000C, 0, 1, 0, 0, 0, 0))
            self.assertFalse(inspect_object(path)['instruction_baseline_audited'])

    def test_multiple_targets_are_bounded_and_cannot_be_make_options(self):
        for names in ((), ('../escape.iig.cpp',), ('--option.iig.cpp',), ('same.iig.cpp',) * 2,
                      tuple(f'Class{number}.iig.cpp' for number in range(18))):
            with self.assertRaisesRegex(ValueError, 'unsafe or unbounded'):
                object_command(Path('/s'), Path('/b'), Path('/g'), 'iphoneos', '/a', names)
        command = object_command(Path('/s'), Path('/b'), Path('/g'), 'iphoneos', '/a',
                                 ('OSObject.iig.cpp', 'OSAction.iig.cpp'))
        self.assertIn('--keep-going', command)
        self.assertEqual(command[-2:], ['OSObject.iig.cpo', 'OSAction.iig.cpo'])

    def test_other_setup_failures_never_start_the_candidate_compile(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('tools.probe_xnu_rpc.check', return_value={
                'configuration_generated': False, 'blockers': ['unrelated error']}), \
                    patch('tools.probe_xnu_rpc.run_phase') as run:
                report = probe(Path(directory), 'iphoneos')
                self.assertFalse(report['passed'])
                self.assertFalse(report['boot_approved'])
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
