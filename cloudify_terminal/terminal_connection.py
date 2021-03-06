# Copyright (c) 2016-2017 Cloudify Platform Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import paramiko
import os
import time
from StringIO import StringIO
from cloudify import exceptions as cfy_exc

DEFAULT_PROMT = ["#", "$"]


# recoverable error based on warning
class RecoverableWarning(cfy_exc.RecoverableError):
    pass


class BaseConnection(object):

    # connection
    conn = None

    # global settings
    logger = None
    log_file_name = None

    # buffer for same packages, will save partial packages between calls
    buff = ""

    def __init__(self, logger=None, log_file_name=None):
        self.logger = logger
        self.log_file_name = log_file_name
        self.conn = None
        self.buff = ""

    # work with log
    def _write_to_log(self, text, output=True):
        # write to log communication dump
        if not self.log_file_name:
            return
        if output:
            # we really want to see what server do before finish
            self.logger.debug(repr(text))
        log_file_name = self.log_file_name + ('' if output else ".in")
        try:
            dir = os.path.dirname(log_file_name)
            if not os.path.isdir(dir):
                os.makedirs(dir)
            with open(log_file_name, 'a+') as file:
                file.write(text)
        except Exception as e:
            if self.logger:
                self.logger.info(str(e))

    # connection function
    def _conn_send(self, message):
        curr_pos = 0
        while curr_pos < len(message):
            send_size = self.conn.send(message[curr_pos:])
            if send_size <= 0:
                send_size = 0
                if self.logger:
                    self.logger.info("We have issue with send!")
                time.sleep(1)
            # write part that already sent
            self._write_to_log(message[curr_pos:curr_pos + send_size], False)
            # save current size of sent block
            curr_pos += send_size
            if self.conn.closed:
                return

    def _conn_recv(self, size):
        recieved = self.conn.recv(size)
        self._write_to_log(recieved)
        if not recieved:
            if self.logger:
                self.logger.warn("We have empty response.")
            time.sleep(1)
        return recieved

    def is_closed(self):
        if self.conn:
            return self.conn.closed
        return True

    def _conn_close(self):
        try:
            if self.conn:
                # sometime code can't close in time
                self.conn.close()
        finally:
            pass

    def _send_response(self, line, responses):
        # return position next to question
        if responses:
            for response in responses:
                # question check
                question_pos = line.find(response['question'])
                if question_pos != -1:
                    # response to question
                    self._conn_send(response.get('answer', ""))
                    if response.get('newline', False):
                        self._conn_send("\n")
                    return question_pos + len(response['question'])
        return -1

    # search/cleanup in buf
    def _find_any_in(self, buff, promt_check):
        for code in promt_check:
            position = buff.find(code)
            if position != -1:
                return position
        # no promt codes
        return -1

    def _delete_backspace(self, text):
        # delete all invisible chars
        backspace = text.find("\b")
        while backspace != -1:
            if backspace == 0:
                text = text[1:]
            else:
                text = text[:backspace - 1] + text[backspace + 1:]
            backspace = text.find("\b")
        return text


class RawConnection(BaseConnection):

    # ssh connection
    ssh = None

    def connect(self, ip, user, password=None, key_content=None, port=22,
                prompt_check=None):
        """open connection"""
        if not prompt_check:
            prompt_check = DEFAULT_PROMT

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if key_content:
            key = paramiko.RSAKey.from_private_key(
                StringIO(key_content)
            )
            self.ssh.connect(ip, username=user, pkey=key, port=port, timeout=5,
                             allow_agent=False)
        else:
            self.ssh.connect(ip, username=user, password=password, port=port,
                             timeout=5, allow_agent=False, look_for_keys=False)

        self.conn = self.ssh.invoke_shell()

        while self._find_any_in(self.buff, prompt_check) == -1:
            self.buff += self._conn_recv(256)
            self.buff = self._delete_backspace(self.buff)

        self.hostname = ""
        # looks as we have some hostname
        code_position = self._find_any_in(self.buff, prompt_check)
        if code_position != -1:
            self.hostname = self.buff[:code_position].strip()
            self.buff = self.buff[code_position + 1:]
            lines = self.hostname.split("\n")
            self.hostname = lines[-1]
            if self.logger:
                self.logger.info("Wellcome message: " + "\n".join(lines[:-1]))
        return self.hostname

    def _cleanup_response(self, text, prefix, warning_examples,
                          error_examples, critical_examples):
        if (
            not error_examples and
            not warning_examples and
            not critical_examples
        ):
            return text.strip()

        # check command echo
        have_correct_prefix = False
        prefix_pos = text.find(prefix)
        if prefix_pos == -1:
            if self.logger:
                self.logger.debug(
                    "Have not found '%s' in response: '%s'" % (
                        prefix, repr(text)
                    )
                )
        else:
            if text[:prefix_pos].strip():
                if self.logger:
                    self.logger.debug(
                        "Some mess before '%s' in response: '%s'" % (
                            prefix, repr(text)
                        )
                    )
            else:
                have_correct_prefix = True

        if have_correct_prefix:
                # looks as we have correct line
                response = text[prefix_pos + len(prefix):]
        else:
            # skip first line(where must be echo from commands input)
            if "\n" in text:
                response = text[text.find("\n"):]
            else:
                response = text

        # check for warnings started only from new line
        if warning_examples:
            warnings_with_new_line = ["\n" + warning
                                      for warning in warning_examples]
            if self._find_any_in(response, warnings_with_new_line) != -1:
                # close is not needed, we will rerun later
                raise RecoverableWarning(
                    "Looks as we have warning in response: %s" % (text)
                )
        # check for errors started only from new line
        if error_examples:
            errors_with_new_line = ["\n" + error for error in error_examples]
            if self._find_any_in(response, errors_with_new_line) != -1:
                if not self.is_closed():
                    self.close()
                raise cfy_exc.RecoverableError(
                    "Looks as we have error in response: %s" % (text)
                )
        # check for criticals started only from new line
        if critical_examples:
            criticals_with_new_line = ["\n" + critical
                                       for critical in critical_examples]
            if self._find_any_in(response, criticals_with_new_line) != -1:
                if not self.is_closed():
                    self.close()
                raise cfy_exc.NonRecoverableError(
                    "Looks as we have critical in response: %s" % (text)
                )
        return response.strip()

    def run(self, command, prompt_check=None, warning_examples=None,
            error_examples=None, critical_examples=None,
            responses=None):
        if not prompt_check:
            prompt_check = DEFAULT_PROMT

        response_prefix = command.strip()
        self._conn_send(response_prefix + "\n")

        if self.conn.closed:
            return ""

        have_prompt = False

        message_from_server = ""

        while not have_prompt:
            while self._find_any_in(self.buff, prompt_check + ["\n"]) == -1:
                self.buff += self._conn_recv(1024)
                self.buff = self._delete_backspace(self.buff)
                # check for close, and only after that for responses
                if self.conn.closed:
                    message_from_server += self.buff
                    return self._cleanup_response(
                        text=message_from_server,
                        prefix=response_prefix,
                        warning_examples=warning_examples,
                        error_examples=error_examples,
                        critical_examples=critical_examples)
                # if we have something like question
                # we can skip check for promt or new line
                if responses:
                    search_list = [res['question'] for res in responses]
                    if self._find_any_in(self.buff, search_list) != -1:
                        break

            # separate finished lines from raw block
            while self.buff.find("\n") != -1:
                line = self.buff[:self.buff.find("\n") + 1]
                self.buff = self.buff[len(line):]
                message_from_server += line
                # we have in current line question?
                self._send_response(line, responses)

            # we have in buff question?
            question_mark = self._send_response(self.buff, responses)
            if question_mark != -1:
                line = self.buff[:question_mark]
                self.buff = self.buff[question_mark:]
                message_from_server += line
                continue

            # last line without new line at the end
            code_position = self._find_any_in(self.buff, prompt_check)
            if code_position != -1:
                have_prompt = True
                self.hostname = self.buff[:code_position]
                self.buff = self.buff[code_position + 1:]

            if self.conn.closed:
                return self._cleanup_response(
                    text=message_from_server,
                    prefix=response_prefix,
                    warning_examples=warning_examples,
                    error_examples=error_examples,
                    critical_examples=critical_examples)
        return self._cleanup_response(text=message_from_server,
                                      prefix=response_prefix,
                                      warning_examples=warning_examples,
                                      error_examples=error_examples,
                                      critical_examples=critical_examples)

    def close(self):
        """close connection"""
        self._conn_close()
        if self.ssh:
            self.ssh.close()

    def __del__(self):
        """Close connections for sure"""
        self.close()
