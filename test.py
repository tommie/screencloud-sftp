#!/usr/bin/env python3

import unittest
from unittest.mock import ANY, MagicMock, patch

class SFTPUploaderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # __import__ only resolves modules once, so we cannot mock
        # modules in setUp() and then re-import. So we use setUpClass
        # instead.
        cls._pythonqt_mock = MagicMock()
        cls._qtcore_mock = MagicMock()
        cls._qtgui_mock = MagicMock()
        cls._qtuitools_mock = MagicMock()
        cls._screencloud_mock = MagicMock()
        cls._ssh2_mock = MagicMock()
        cls._exceptions_mock = MagicMock()
        cls._session_mock = MagicMock()
        cls._sftp_mock = MagicMock()
        patch.dict('sys.modules', {
            'PythonQt': cls._pythonqt_mock,
            'PythonQt.QtCore': cls._qtcore_mock,
            'PythonQt.QtGui': cls._qtgui_mock,
            'PythonQt.QtUiTools': cls._qtuitools_mock,
            'ScreenCloud': cls._screencloud_mock,
            'ssh2': cls._ssh2_mock,
            'ssh2.exceptions': cls._exceptions_mock,
            'ssh2.session': cls._session_mock,
            'ssh2.sftp': cls._sftp_mock,
        }).start()
        cls._exceptions_mock.FileError = Exception
        cls._exceptions_mock.SFTPProtocolError = Exception
        cls._exceptions_mock.SSH2Error = Exception
        patch('main.workingDir', '/workingdir', create=True).start()
        cls._main = __import__('main')

    @classmethod
    def tearDownClass(cls):
        patch.stopall()

    def setUp(self):
        self.settings = {
            'host': 'testhost',
            'port': 42,
            'username': 'testusername',
            'password': 'testpassword',
            'keyfile': 'testkeyfile',
            'passphrase': 'testpassphrase',
            'url': 'http://testurl/_/',
            'folder': '/test',
            'name-format': 'testformat',
            'auth-method': 'Password',
        }
        self._qtcore_mock.QSettings.return_value.value = self.settings.get
        self.uploader = self._main.SFTPUploader()

    def test_showSettingsUI(self):
        self.uploader.showSettingsUI(MagicMock())

    def test_isConfigured_all(self):
        self.assertTrue(self.uploader.isConfigured())

    def test_isConfigured_host(self):
        del self.settings["host"]
        self.assertFalse(self.uploader.isConfigured())

    def test_isConfigured_username(self):
        del self.settings["username"]
        self.assertFalse(self.uploader.isConfigured())

    def test_isConfigured_password_keyfile(self):
        del self.settings["password"]
        del self.settings["keyfile"]
        self.assertFalse(self.uploader.isConfigured())

    def test_isConfigured_folder(self):
        del self.settings["folder"]
        self.assertFalse(self.uploader.isConfigured())

    @patch('ScreenCloud.formatFilename')
    def test_getFilename(self, format_filename_mock):
        format_filename_mock.return_value = 'testfilename'

        self.assertEqual(self.uploader.getFilename(), 'testfilename')
        format_filename_mock.assert_called_with('testformat')

    @patch('socket.socket')
    def test_upload(self, socket_mock):
        screenshot_mock = MagicMock()
        self.assertTrue(self.uploader.upload(screenshot_mock, "a/b.png"))

        sock = socket_mock.return_value.__enter__.return_value
        sock.connect.assert_called_with(('testhost', 42))

        screenshot_mock.save.assert_called_with(
            self._qtcore_mock.QBuffer.return_value,
            self._screencloud_mock.getScreenshotFormat.return_value)

        session = self._session_mock.Session.return_value
        session.handshake.assert_called_with(sock)
        session.userauth_password.assert_called_with('testusername', 'testpassword')

        sftp = session.sftp_init.return_value
        sftp.stat.assert_called_with('/test/a')
        sftp.mkdir.assert_not_called()
        sftp.open.assert_called_with('/test/a/b.png', ANY, ANY)
        sftp.open.return_value.__enter__.return_value.write.assert_called_with(
            self._qtcore_mock.QByteArray.return_value.data.return_value)
        sftp.get_channel.return_value.close.assert_called_with()
        session.disconnect.assert_called_with()

        self._screencloud_mock.setUrl.assert_called_with('http://testurl/_/a/b.png')
        self._screencloud_mock.setError.assert_not_called()

if __name__ == "__main__":
    unittest.main()
