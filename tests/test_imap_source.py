"""IMAP connection cleanup used by mailbox tests and reconnects."""
import unittest
from unittest.mock import patch

from mailcheck.sources.base import SourceError
from mailcheck.sources.imap import IMAPSource


class ImapConnectionTests(unittest.TestCase):
    def source(self):
        return IMAPSource(host="imap.gmail.com", port=993, username="me@gmail.com", password="app-password")

    def test_failed_login_closes_the_connection(self):
        with patch("mailcheck.sources.imap.MailBox") as mailbox:
            mailbox.return_value.login.side_effect = OSError("Authentication failed")
            with self.assertRaises(SourceError):
                self.source().test()
            mailbox.return_value.logout.assert_called_once()

    def test_failed_folder_selection_closes_the_connection(self):
        with patch("mailcheck.sources.imap.MailBox") as mailbox:
            mailbox.return_value.folder.set.side_effect = OSError("Folder unavailable")
            with self.assertRaises(SourceError):
                self.source().test()
            mailbox.return_value.logout.assert_called_once()

    def test_cleanup_failure_does_not_hide_login_error(self):
        with patch("mailcheck.sources.imap.MailBox") as mailbox:
            mailbox.return_value.login.side_effect = OSError("Authentication failed")
            mailbox.return_value.logout.side_effect = OSError("Socket closed")
            with self.assertRaisesRegex(SourceError, "Authentication failed"):
                self.source().test()
            mailbox.return_value.client.shutdown.assert_called_once()
