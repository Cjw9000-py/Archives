import os
import io
import string
import sys
import zlib
import shutil
import logging
import tempfile
import unittest
import traceback

from io import BytesIO
from static import (
    _move_stream,
    _lock,
)

from os.path import *
from static import *


logging.basicConfig(level='DEBUG', stream=sys.stdout)


class DebugStream(io.BytesIO):
    def __init__(self, initial: bytes = None):
        super(DebugStream, self).__init__(initial)
        self.traces = list()
        self.limit = 4

    def _tb(self):
        extraction = traceback.extract_stack(limit=self.limit + 2)
        extraction = extraction[:-2]
        return extraction

    def read(self, __size=...) -> bytes:
        ret = super(DebugStream, self).read(__size)
        self.traces.append(('read', (__size,), ret, self._tb()))
        return ret

    def write(self, __buffer) -> int:
        ret = super(DebugStream, self).write(__buffer)
        self.traces.append(('write', (__buffer,), ret, self._tb()))
        return ret

    def seek(self, __offset: int, __whence: int = 0) -> int:
        ret = super(DebugStream, self).seek(__offset, __whence)
        self.traces.append(('seek', (__offset, __whence), ret, self._tb()))
        return ret

    def print_traces(self, file=sys.stdout):
        for name, args, ret, tb in self.traces:
            print('\n', '#' * shutil.get_terminal_size().columns, sep='')
            print(name, '(', ', '.join((str(i) for i in args)), ') -> ', ret, sep='', file=file)
            traceback.print_list(tb, file=file)

        self.traces = list()


def clear(p, t=False):
    shutil.rmtree(p, ignore_errors=True)
    if not t:
        try: os.mkdir(p)
        except FileExistsError: ...


class TestHelpers(unittest.TestCase):
    def test_move_stream(self):
        src = BytesIO(b'A' * 150)
        dest = BytesIO()

        assert _move_stream(src, dest, 67) == 150
        assert src.getvalue() == dest.getvalue()

        src = BytesIO(b'A' * 1000)
        dest = BytesIO()

        assert _move_stream(src, dest, 53, 567) == 567
        assert src.getvalue()[:567] == dest.getvalue()

        src = BytesIO(b'A' * 150)
        dest = BytesIO()
        crc = 0

        def cb(c):
            nonlocal crc
            crc = zlib.crc32(c, crc)

        assert _move_stream(src, dest, 99, 146, cb)
        assert src.getvalue()[:146] == dest.getvalue()

        crc2 = zlib.crc32(src.getvalue()[:146])
        assert crc2 == crc, (crc2, crc)

    def test_lock(self):
        class TestClass:
            def __init__(self):
                self._stream = BytesIO(b'A' * 100)

            @_lock
            def do_smt(self):
                _ = self._stream.read()
                self._stream.write(_)

        cls = TestClass()

        start = cls._stream.tell()
        cls.do_smt()
        end = cls._stream.tell()

        assert start == end

    def test_is_archive(self):
        s = BytesIO(MAGIC)
        assert is_archive(s)
        s.seek(0)
        s.write(os.urandom(100))
        assert not is_archive(s)


class TestStaticArchive(unittest.TestCase):
    def test_init(self):
        s = BytesIO()
        StaticArchive(s, 'w')
        pth = join(tempfile.gettempdir(), 'TestStaticArchive_init.tmp')
        StaticArchive(pth, 'w').close()

        try:
            os.remove(pth)
        except (FileNotFoundError, PermissionError):
            pass

        StaticArchive(s, 'a')
        StaticArchive(s, 'r')

        StaticArchive(s, 'r',
                      size_mode=SizeMode.m16,
                      write_crc=False,  # ignored
                      checks=False).close()

    def test_sig_helpers(self):
        try:
            s = DebugStream()
            sa = StaticArchive(s, 'w')
            s.truncate(0)

            sa._write_sig()
            sa._check_sig()

            before = s.getvalue()
            sa._load_sig()
            sa._write_sig()
            after = s.getvalue()
            assert before == after, (before, after)
        except Exception:
            if 's' in locals():
                s.print_traces()
            raise

    def test_hdr_helpers(self):
        def test_mode(mode):
            sa = StaticArchive(BytesIO(), 'w', size_mode=mode)
            sa._stream.truncate(0)

            args = 'test', 0xFFFF_FFFF, 42
            sa._write_hdr(*args)
            sa._stream.seek(0)
            args2 = sa._read_hdr()
            assert args2 == args, (args2, args, m)

        for m in range(3):
            test_mode(m)

    def test_context_manager(self):
        with StaticArchive(BytesIO(), 'w') as sa:
            assert sa._closed is False
        assert sa._closed is True

    def test_append(self):
        # read only
        s = BytesIO()
        StaticArchive(s, 'w').flush()  # make the stream a valid archive
        sa = StaticArchive(s, 'r')

        try:
            sa.append('test', b'testdata')
        except TypeError:
            pass

        sa = StaticArchive(BytesIO(), 'w')

        test_files = [(os.getrandom(10).hex(), b'A' * 100) for i in range(100)]

        for name, data in test_files:
            sa.append(name, data)

        assert sa.file_count == len(test_files)
        for file, info in zip(test_files, sa.file_infos()):
            assert file[0] == info.name, (file[0], info.name)
            assert len(file[1]) == info.size, (len(file[1]), info.size)
            csum = zlib.crc32(file[1])
            assert csum == info.crc, (csum, info.crc)

    def test_read(self):
        sa = StaticArchive(BytesIO(), 'w')
        data = b'A' * 100
        sa.append('test', data)
        assert sa.read('test') == data
        assert sa.read(sa.file_info('test')) == data

        dest = io.BytesIO()
        sa.read_into('test', dest)
        assert dest.getvalue() == data

    def test_add(self):
        temp_path = join(tempfile.gettempdir(), 'test_static_add')
        clear(temp_path)

        tf_path = join(temp_path, 'test_file.txt')
        with open(tf_path, 'w') as tf:
            tf.write('ABC' * 100)

        with StaticArchive(join(temp_path, 'test_arch.static.arch'), 'w') as sa:
            sa.add(tf_path)

            assert sa.file_count == 1, sa.file_count
            assert tuple(sa.file_names())[0] == tf_path, tuple(sa.file_names())[0]

            rec_path = join(temp_path, 'test_recurse')
            clear(rec_path)

            for i in range(10):
                with open(join(rec_path, 'test_file.' + str(i)), 'wb') as f:
                    f.write(os.urandom(100))

            sa.add(rec_path)
            assert sa.file_count == 11, sa.file_count

        with StaticArchive(join(temp_path, 'test_arch.static.arch'), 'w') as sa:
            sa.add(rec_path, only_names=True)

            for i, info in enumerate(sa.file_infos()):
                assert info.name[-1] in string.digits, info.name

        clear(temp_path, t=True)

    @staticmethod
    def _gen_files(tp, count, data_amount):
        files_path = join(tp, 'test_files')
        clear(files_path)

        logging.info('Generating test files. This test will take about 2Mb of disk space. All files will be cleared.')
        for i in range(count):
            with open(join(files_path, str(i)), 'wb') as f:
                f.write(b'A' * data_amount)

        return files_path

    def test_bar(self):
        # caution this may be io expensive

        temp_path = join(tempfile.gettempdir(), 'test_static_bar')
        clear(temp_path)
        files_path = self._gen_files(temp_path, 100_000, 1000)

        with StaticArchive(join(temp_path, 'test_static.arch'), 'w',
                           size_mode=SizeMode.m16, write_crc=False, checks=False) as sa:
            sa.add(files_path, verbose=True, only_names=True)

        logging.info('Removing generated files...')
        clear(temp_path, t=True)

    def test_extract(self):
        temp_path = join(tempfile.gettempdir(), 'test_static_extract')
        clear(temp_path)
        files_path = self._gen_files(temp_path, 10_000, 100)

        extract_path = join(temp_path, 'test_extract')
        clear(extract_path)

        with StaticArchive(join(temp_path, 'test_static.arch'), 'w',
                           size_mode=SizeMode.m16, write_crc=False, checks=False) as sa:
            sa.add(files_path, verbose=True, only_names=True)

        with StaticArchive(join(temp_path, 'test_static.arch'), 'r',
                           checks=False) as sa:
            sa.extract(extract_path, verbose=True)

        clear(temp_path, t=True)

    def test_create_samples(self):
        try:
            os.mkdir('samples')
        except FileExistsError:
            pass

        for mode in range(3):
            with StaticArchive(f'samples/sample.static.{SizeMode(mode).name}.arch', 'w', size_mode=SizeMode(mode), write_crc=False) as sa:
                for i in range(5):
                    sa.append('A' * 5, b'B' * 10)

        for mode in range(3):
            with StaticArchive(f'samples/sample.static.{SizeMode(mode).name}.crc.arch', 'w', size_mode=SizeMode(mode)) as sa:
                for i in range(5):
                    sa.append('A' * 5, b'B' * 10)


if __name__ == '__main__':
    unittest.main()
