import struct
import unittest

from tools.mido_vm_geometry import l2_count
from tools.mido_vm_executable_reference import ExecutableReference
from tests import test_mido_vm_executable_reference as executable_tests


class VMGeometryTests(unittest.TestCase):
    def test_both_original_slide_geometries(self):
        virtual,physical,top = 0xfffffff007000000,0x11200000,0x12401000
        for slide,expected in ((0,1),(0x3ffff000,2)):
            physmap = virtual+top-physical+slide
            self.assertEqual(l2_count(virtual,physical,top,physmap,physmap+0x3000000,0x2000000),expected)

    def test_bad_geometry_not_accepted_as_extra_allocation(self):
        virtual,physical,top = 0xfffffff007000000,0x11200000,0x12401000
        base = virtual+top-physical
        for physmap,static_end,memory in ((base+1,base+1+0x3000000,0x2000000),
                (base+0x40000000,base+0x43000000,0x2000000),
                (base,base+0x3000001,0x2000000),(base,base+0x3000000,0x1000000)):
            with self.assertRaisesRegex(ValueError,"Unreviewed"):
                l2_count(virtual,physical,top,physmap,static_end,memory)

    def test_two_l2_roots_shift_l3_pages_but_preserve_leaf_permissions(self):
        original = executable_tests.ExecutableReferenceTests().reference()
        reference = ExecutableReference(list(original.segments.values()),original.virtual,original.physical,original.top,2)
        pages = reference.expected("vm-data-mapped")
        self.assertEqual(len(pages),32768)
        self.assertEqual(struct.unpack_from("<Q",pages,4096+193*8)[0],0x2000000012404003)
        self.assertFalse(any(pages[12288:16384]))
        self.assertEqual(struct.unpack_from("<Q",pages,8192+56*8)[0],0x12405003)
        self.assertEqual(struct.unpack_from("<Q",pages,0x124060a0-reference.top)[0],0x0040000011414683)


if __name__ == "__main__":
    unittest.main()
