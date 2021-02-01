#!/usr/bin/env python3
import contextlib, socket, sys, time
from urllib.parse import urljoin

import ScreenCloud

from PythonQt.QtCore import QBuffer, QByteArray, QFile, QIODevice, QSettings
from PythonQt.QtGui import QDesktopServices, QFileDialog
if not hasattr(QDesktopServices, 'storageLocation'):
	# storageLocation is deprecated in QT5.
	from PythonQt.QtCore import QStandardPaths
from PythonQt.QtUiTools import QUiLoader
import ssh2
from ssh2.exceptions import SFTPError, SSH2Error
from ssh2.session import Session
from ssh2.sftp import LIBSSH2_FXF_CREAT, LIBSSH2_FXF_WRITE, \
					 LIBSSH2_SFTP_S_IRUSR, LIBSSH2_SFTP_S_IRGRP, \
					 LIBSSH2_SFTP_S_IWUSR, LIBSSH2_SFTP_S_IROTH, \
					 LIBSSH2_SFTP_S_IXUSR, LIBSSH2_SFTP_S_IXGRP, \
					 LIBSSH2_SFTP_S_IXOTH

_SFTP_S_IRUGO = LIBSSH2_SFTP_S_IRUSR | LIBSSH2_SFTP_S_IRGRP | LIBSSH2_SFTP_S_IROTH
_SFTP_S_IXUGO = LIBSSH2_SFTP_S_IXUSR | LIBSSH2_SFTP_S_IXGRP | LIBSSH2_SFTP_S_IXOTH

class SFTPUploader():
	def __init__(self):
		self.uil = QUiLoader()
		self.__loadSettings()

	def showSettingsUI(self, parentWidget):
		self.parentWidget = parentWidget
		self.settingsDialog = self.uil.load(QFile(workingDir + "/settings.ui"), parentWidget)
		self.settingsDialog.group_server.combo_auth.connect("currentIndexChanged(QString)", self.__authMethodChanged)
		self.settingsDialog.group_server.button_browse.connect("clicked()", self.__browseForKeyfile)
		self.settingsDialog.group_location.input_name.connect("textChanged(QString)", self.__nameFormatEdited)
		self.settingsDialog.connect("accepted()", self.__saveSettings)
		self.__loadSettings()
		self.__updateUi()
		self.settingsDialog.group_server.input_host.text = self.host
		self.settingsDialog.group_server.input_port.value = self.port
		self.settingsDialog.group_server.input_username.text = self.username
		self.settingsDialog.group_server.input_password.text = self.password
		self.settingsDialog.group_server.input_keyfile.text = self.keyfile
		self.settingsDialog.group_server.input_passphrase.text = self.passphrase
		self.settingsDialog.group_location.input_folder.text = self.folder
		self.settingsDialog.group_location.input_url.text = self.url
		self.settingsDialog.group_location.input_name.text = self.nameFormat
		self.settingsDialog.group_server.combo_auth.setCurrentIndex(self.settingsDialog.group_server.combo_auth.findText(self.authMethod))
		self.settingsDialog.open()

	def __loadSettings(self):
		settings = QSettings()
		settings.beginGroup("uploaders")
		settings.beginGroup("sftp")
		self.host = settings.value("host", "")
		self.port = int(settings.value("port", 22))
		self.username = settings.value("username", "")
		self.password = settings.value("password", "")
		self.keyfile = settings.value("keyfile", "")
		self.passphrase = settings.value("passphrase", "")
		self.url = settings.value("url", "")
		self.folder = settings.value("folder", "")
		self.nameFormat = settings.value("name-format", "Screenshot at %H-%M-%S")
		self.authMethod = settings.value("auth-method", "Password")
		settings.endGroup()
		settings.endGroup()

	def __saveSettings(self):
		settings = QSettings()
		settings.beginGroup("uploaders")
		settings.beginGroup("sftp")
		settings.setValue("host", self.settingsDialog.group_server.input_host.text)
		settings.setValue("port", int(self.settingsDialog.group_server.input_port.value))
		settings.setValue("username", self.settingsDialog.group_server.input_username.text)
		settings.setValue("password", self.settingsDialog.group_server.input_password.text)
		settings.setValue("keyfile", self.settingsDialog.group_server.input_keyfile.text)
		settings.setValue("passphrase", self.settingsDialog.group_server.input_passphrase.text)
		settings.setValue("url", self.settingsDialog.group_location.input_url.text)
		settings.setValue("folder", self.settingsDialog.group_location.input_folder.text)
		settings.setValue("name-format", self.settingsDialog.group_location.input_name.text)
		settings.setValue("auth-method", self.settingsDialog.group_server.combo_auth.currentText)
		settings.endGroup()
		settings.endGroup()

	def __updateUi(self):
		self.settingsDialog.group_server.label_password.setVisible(self.authMethod == "Password")
		self.settingsDialog.group_server.input_password.setVisible(self.authMethod == "Password")
		self.settingsDialog.group_server.label_keyfile.setVisible(self.authMethod == "Key")
		self.settingsDialog.group_server.input_keyfile.setVisible(self.authMethod == "Key")
		self.settingsDialog.group_server.button_browse.setVisible(self.authMethod == "Key")
		self.settingsDialog.group_server.label_passphrase.setVisible(self.authMethod == "Key")
		self.settingsDialog.group_server.input_passphrase.setVisible(self.authMethod == "Key")
		self.settingsDialog.adjustSize()

	def __authMethodChanged(self, method):
		self.authMethod = method
		self.__updateUi()

	def __browseForKeyfile(self):
		filename = QFileDialog.getOpenFileName(self.settingsDialog, "Select Keyfile...", _getHomeDirectory(), "*")
		if filename:
			self.settingsDialog.group_server.input_keyfile.setText(filename)

	def __nameFormatEdited(self, nameFormat):
		self.settingsDialog.group_location.label_example.setText(ScreenCloud.formatFilename(nameFormat))

	def isConfigured(self):
		self.__loadSettings()
		return not(not self.host or not self.username or not (self.password or self.keyfile) or not self.folder)

	def getFilename(self):
		self.__loadSettings()
		return ScreenCloud.formatFilename(self.nameFormat)

	def upload(self, screenshot, name):
		"""Uploads the given QImage using SFTP, with the given remote name.

                The name should already be formatted using getFilename().

		Returns true for success and false on error.
		"""
		try:
			self.__upload(screenshot, name)
			return True
		except Exception as exc:
			if str(exc):
				ScreenCloud.setError(str(exc))
			else:
				ScreenCloud.setError(str(type(exc)))
			return False

	def __upload(self, screenshot, name):
		self.__loadSettings()
		with self.__openSftpSubsystem() as sftp:
			mode = _SFTP_S_IRUGO | LIBSSH2_SFTP_S_IWUSR
			# The trailing slash ensures folder is interpreted
			# as a directory. urljoin handles double-slash well.
			destination = urljoin(self.folder + '/', name)
			try:
				_makeRemoteDirs(sftp, _dirname(destination), mode | _SFTP_S_IXUGO)
				with sftp.open(destination, LIBSSH2_FXF_CREAT | LIBSSH2_FXF_WRITE, mode) as remote_fh:
					remote_fh.write(_serializeQImage(screenshot, ScreenCloud.getScreenshotFormat()))
			except IOError as exc:
				raise IOError("Failed to write {}. Check permissions.".format(destination)) from exc

		if self.url:
			# The trailing slash ensures url is interpreted
			# as a directory. urljoin handles double-slash well.
			ScreenCloud.setUrl(urljoin(self.url + '/', name))

	@contextlib.contextmanager
	def __openSftpSubsystem(self):
		"""Opens an SFTP subsystem based on settings."""
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
			sock.connect((self.host, self.port))
			session = Session()
			try:
				session.handshake(sock)
				if self.authMethod == "Password":
					session.userauth_password(self.username, self.password)
				else:
					session.userauth_publickey_fromfile(self.username, self.keyfile, passphrase=self.passphrase)

				sftp = session.sftp_init()
				try:
					yield sftp
				finally:
					sftp.get_channel().close()
			except SSH2Error as exc:
				# ssh2-python doesn't set an exception message and instead stores
				# it in the session object.
				msg = session.last_error()
				if msg:
					exc.args = (msg.decode("utf-8"),)
				raise
			finally:
				session.disconnect()


def _getHomeDirectory():
	"""Returns the user's home directory."""
	if hasattr(QDesktopServices, 'storageLocation'):
		# QT4
		return QDesktopServices.storageLocation(QDesktopServices.HomeLocation)
	return QStandardPaths.writableLocation(QStandardPaths.HomeLocation)

def _serializeQImage(image, format):
	"""Converts the provided QImage to bytes in the given format."""
	data = QByteArray()
	buffer = QBuffer(data)
	buffer.open(QIODevice.WriteOnly)
	image.save(buffer, format)
	return data.data()

def _makeRemoteDirs(sftp, path, mode):
        """Ensures a directory exists, creating parents as needed."""
        try:
                sftp.stat(path)
        except SFTPError:
                parent = _dirname(path)
                if parent in ("", "/"):
                        raise
                _makeRemoteDirs(sftp, parent, mode)
                sftp.mkdir(path, mode)

def _dirname(path):
        """Like os.path.dirname(), but always operates on POSIX paths."""
        if "/" not in path:
                return ""

        dir = path.rsplit("/", 1)[0]
        return dir if dir else "/"
