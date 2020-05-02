# -*- coding: utf-8 -*-
"""Test the capabilities of the ResourceManager.

"""
import gc
import logging
import unittest

from pyvisa import InvalidSession, ResourceManager, VisaIOError, errors, logger
from pyvisa.constants import AccessModes, InterfaceType, StatusCode
from pyvisa.highlevel import VisaLibraryBase
from pyvisa.rname import ResourceName
from pyvisa.testsuite import BaseTestCase

from . import RESOURCE_ADDRESSES, require_virtual_instr


@require_virtual_instr
class TestResourceManager(unittest.TestCase):
    """Test the pyvisa ResourceManager.

    """

    def setUp(self):
        """Create a ResourceManager with the default backend library.

        """
        self.rm = ResourceManager()

    def tearDown(self):
        """Close the ResourceManager.

        """
        if self.rm is not None:
            self.rm.close()
            del self.rm
            gc.collect()

    def test_lifecycle(self):
        """Test creation and closing of the resource manager.

        """
        self.assertIsNotNone(self.rm.session)
        self.assertIsNotNone(self.rm.visalib)
        self.assertIs(self.rm, self.rm.visalib.resource_manager)
        self.assertFalse(self.rm.list_opened_resources())

        self.assertIs(self.rm.visalib, ResourceManager(self.rm.visalib).visalib)

        with self.assertLogs(level=logging.DEBUG, logger=logger):
            self.rm.close()

        with self.assertRaises(InvalidSession):
            self.rm.session
        self.assertIsNone(self.rm.visalib.resource_manager)

    def test_cleanup_on_del(self):
        """Test that deleting the rm does clean the VISA session

        """
        # The test seems to assert what it should even though the coverage report
        # seems wrong
        rm = self.rm
        self.rm = None
        with self.assertLogs(level=logging.DEBUG, logger=logger) as log:
            del rm
            gc.collect()

        self.assertIn("Closing ResourceManager", log.output[0])

    def test_resource_manager_unicity(self):
        """Test the resource manager is unique per backend as expected.

        """
        new_rm = ResourceManager()
        self.assertIs(self.rm, new_rm)
        self.assertEqual(self.rm.session, new_rm.session)

    def test_str(self):
        """Test computing the string representation of the resource manager

        """
        self.assertRegex(str(self.rm), r"Resource Manager of .*")
        self.rm.close()
        self.assertRegex(str(self.rm), r"Resource Manager of .*")

    def test_repr(self):
        """Test computing the repr of the resource manager

        """
        self.assertRegex(repr(self.rm), r"<ResourceManager\(<.*>\)>")
        self.rm.close()
        self.assertRegex(repr(self.rm), r"<ResourceManager\(<.*>\)>")

    def test_last_status(self):
        """Test accessing the status of the last operation.

        """
        self.assertEqual(self.rm.last_status, StatusCode.success)

        # Access the generic last status through the visalib
        self.assertEqual(self.rm.last_status, self.rm.visalib.last_status)

        # Test accessing the status for an invalid session
        with self.assertRaises(errors.Error) as cm:
            self.rm.visalib.get_last_status_in_session("_nonexisting_")
        self.assertIn("The session", cm.exception.args[0])

    def test_list_resource(self):
        """Test listing the available resources.

        """
        # Default settings
        self.assertSequenceEqual(
            sorted(self.rm.list_resources()),
            sorted(
                [
                    str(ResourceName.from_string(v))
                    for v in RESOURCE_ADDRESSES.values()
                    if v.endswith("INSTR")
                ]
            ),
        )

        # All resources
        self.assertSequenceEqual(
            sorted(self.rm.list_resources("?*")),
            sorted(
                [str(ResourceName.from_string(v)) for v in RESOURCE_ADDRESSES.values()]
            ),
        )

    def test_accessing_resource_infos(self):
        """Test accessing resource infos.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        rinfo_ext = self.rm.resource_info(rname)
        rinfo = self.rm.resource_info(rname, extended=False)

        rname = ResourceName().from_string(rname)
        self.assertEqual(
            rinfo_ext.interface_type,
            getattr(InterfaceType, rname.interface_type.lower()),
        )
        self.assertEqual(rinfo_ext.interface_board_number, int(rname.board))
        self.assertEqual(rinfo_ext.resource_class, rname.resource_class)
        self.assertEqual(rinfo_ext.resource_name, str(rname))

        self.assertEqual(
            rinfo.interface_type, getattr(InterfaceType, rname.interface_type.lower())
        )
        self.assertEqual(rinfo.interface_board_number, int(rname.board))

    def test_listing_resource_infos(self):
        """Test listing resource infos.

        """
        infos = self.rm.list_resources_info()

        for rname, rinfo_ext in infos.items():
            rname = ResourceName().from_string(rname)
            self.assertEqual(
                rinfo_ext.interface_type,
                getattr(InterfaceType, rname.interface_type.lower()),
            )
            self.assertEqual(rinfo_ext.interface_board_number, int(rname.board))
            self.assertEqual(rinfo_ext.resource_class, rname.resource_class)
            self.assertEqual(rinfo_ext.resource_name, str(rname))

    def test_opening_resource(self):
        """Test opening and closing resources.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        rsc = self.rm.open_resource(rname, timeout=1234)

        # Check the resource is listed as opened and the attributes are right.
        self.assertIn(rsc, self.rm.list_opened_resources())
        self.assertEqual(rsc.timeout, 1234)

        # Close the rm to check that we close all resources.
        self.rm.close()

        self.assertFalse(self.rm.list_opened_resources())
        with self.assertRaises(InvalidSession):
            rsc.session

    def test_opening_resource_bad_open_timeout(self):
        """Test opening a resource with a non integer open_timeout.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]

        with self.assertRaises(ValueError) as cm:
            self.rm.open_resource(rname, open_timeout="")

        self.assertIn("integer (or compatible type)", str(cm.exception))

    def test_opening_resource_with_lock(self):
        """Test opening a locked resource

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        rsc = self.rm.open_resource(rname, access_mode=AccessModes.exclusive_lock)
        self.assertEqual(len(self.rm.list_opened_resources()), 1)

        # Timeout when accessing a locked resource
        with self.assertRaises(VisaIOError):
            self.rm.open_resource(rname, access_mode=AccessModes.exclusive_lock)
        self.assertEqual(len(self.rm.list_opened_resources()), 1)

        # Success to access an unlocked resource.
        rsc.unlock()
        with self.rm.open_resource(
            rname, access_mode=AccessModes.exclusive_lock
        ) as rsc2:
            self.assertEqual(len(self.rm.list_opened_resources()), 2)

    def test_opening_resource_specific_class(self):
        """Test opening a resource requesting a specific class.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        with self.assertRaises(TypeError):
            self.rm.open_resource(rname, resource_pyclass=object)

        self.assertEqual(len(self.rm.list_opened_resources()), 0)

    def test_open_resource_unknown_resource_type(self):
        """Test opening a resource for which no registered class exist.

        """
        rc = ResourceManager._resource_classes
        old = rc.copy()

        class FakeResource:
            def __init__(self, *args):
                raise RuntimeError()

        rc[(InterfaceType.unknown, "")] = FakeResource
        del rc[(InterfaceType.tcpip, "INSTR")]

        rm = ResourceManager()
        try:
            with self.assertLogs(level=logging.DEBUG, logger=logger):
                with self.assertRaises(RuntimeError):
                    rm.open_resource("TCPIP::192.168.0.1::INSTR")
        finally:
            ResourceManager._resource_classes = old

    def test_opening_resource_unknown_attribute(self):
        """Test opening a resource and attempting to set an unknown attr.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        with self.assertRaises(ValueError):
            self.rm.open_resource(rname, unknown_attribute=None)

        self.assertEqual(len(self.rm.list_opened_resources()), 0)

    def test_get_instrument(self):
        """Check that we get the expected deprecation warning.

        """
        rname = list(RESOURCE_ADDRESSES.values())[0]
        with self.assertWarns(FutureWarning):
            self.rm.get_instrument(rname)


@require_virtual_instr
class TestResourceParsing(BaseTestCase):
    """Test parsing resources using the builtin mechanism and the VISA lib.

    Those tests require that the interface exist (at least in Keysight
    implementation) so we cannot test arbitrary interfaces (PXI for example).

    """

    def setUp(self):
        """Create a ResourceManager with the default backend library.

        """
        self.rm = ResourceManager()

    def tearDown(self):
        """Close the ResourceManager.

        """
        del self.rm
        gc.collect()

    def test_parse_tcpip_instr(self):
        self._parse_test("TCPIP::192.168.200.200::INSTR")

    def test_parse_tcpip_socket(self):
        self._parse_test("TCPIP::192.168.200.200::7020::SOCKET")

    def _parse_test(self, rn):
        # Visa lib
        p = self.rm.visalib.parse_resource_extended(self.rm.session, rn)

        # Internal
        pb = VisaLibraryBase.parse_resource_extended(
            self.rm.visalib, self.rm.session, rn
        )
        self.assertEqual(p, pb)

        # Non-extended parsing
        # Visa lib
        p = self.rm.visalib.parse_resource(self.rm.session, rn)

        # Internal
        pb = VisaLibraryBase.parse_resource(self.rm.visalib, self.rm.session, rn)
        self.assertEqual(p, pb)
