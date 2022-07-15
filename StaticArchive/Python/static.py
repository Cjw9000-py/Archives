#!/usr/bin/python3

"""
Stacked file entries.

Target -> small header overhead
Usage  -> for long time storage of files without needing fast access of specific files

Pseudo C Code:
enum Mode {
    M16,
    M32,
    M64,
};

// start address 0x00
struct FileSignature {
    char magic[8] = { 0x91, 0xde, 0xee, 0x9c, 0x80, 0x5c, 0x23, 0xe6 };
    uint32 general_purpose;
    uint64 file_count;
    uchar mode; // -> Mode
    uchar crc; // is crc32 used?

};

struct EntryHeader {
    uchar name_size; // max size = 256
    char name[name_size];
    uint32 crc32;

    mode data_size;
    uchar data[data_size];
};

"""

# NOTE: we don't use struct for compatibility.
import io
import os
import shutil
import zlib
import enum
import argparse
import functools
import dataclasses

from typing import Generator, Union, BinaryIO, List
from os.path import join, isfile, isdir, split

BYTE = 1
WORD = 2
DWORD = 4
QWORD = 8
BYTEORDER = 'little'
ENCODING = 'ascii'
BUFFER_SIZE = 200_000

_encode = lambda x, t: x.to_bytes(t, BYTEORDER, signed=False)
_decode = lambda d: int.from_bytes(d, BYTEORDER, signed=False)


MAGIC = b'\x91\xde\xee\x9c\x80\x5c\x23\xe6'
MODE_MASK = 0b1100_0000
CRC_MASK  = 0b0010_0000
CONV_MODE = [WORD, DWORD, QWORD]
READ_OFFSET = len(MAGIC) + DWORD + QWORD + BYTE + BYTE


def _move_stream(src, dest, chunk_size, total=None, fn=None):
    c = 0
    while True:
        ns = chunk_size
        if total is not None:
            ns = chunk_size if total > chunk_size else total

        chunk = src.read(ns)
        if not chunk: break
        c += len(chunk)

        if total is not None:
            total -= len(chunk)

        if fn is not None:
            fn(chunk)
        dest.write(chunk)
    return c


def _lock(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        self = args[0]  # pycharm type hinting issues
        assert self._stream.seekable()
        p = self._stream.tell()
        ret = fn(*args, **kwargs)
        self._stream.seek(p)
        return ret
    return inner


def parse_args():
    parser = argparse.ArgumentParser()


    parser.add_argument(dest='cmd', help="""
    Possible Commands:
        - create   | c
        - append   | a
        - extract  | e
        - list     | l
        - validate | v
    """)
    parser.add_argument('-s', '--source', dest='src', required=False, help='Input files or directories.')

    mode_group = parser.add_argument_group('Size Mode')
    mode_group.add_argument('-M16', dest='M16', action='store_true', help='For 16 bit mode.')
    mode_group.add_argument('-M32', dest='M32', action='store_true', help='For 32 bit mode.')
    mode_group.add_argument('-M64', dest='M64', action='store_true', help='For 64 bit mode.')

    flags_group = parser.add_argument_group('Flags')
    flags_group.add_argument('-f', '--file', dest='file', help='The archive file.', required=True)
    flags_group.add_argument('-g', dest='gen_purpose', help='Value for the general purpose field inside the header.')
    flags_group.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='Be verbose.')
    flags_group.add_argument('-l', '--limit', dest='limited_files', nargs='*', help='Files that should be extracted.')
    flags_group.add_argument('-n', '--names', dest='names', action='store_true',
                             help='Only add (base)names to the archive, not the relative path of each file')

    validation_group = parser.add_argument_group('Validation')
    validation_group.add_argument('-r', '--no-crc', dest='crc', action='store_false',
                                  help='Disable writing a crc32.')
    validation_group.add_argument('-c', '--no-checks', dest='checks', action='store_false',
                                  help='Disable crc32 checks.')
    return parser.parse_args()


def is_archive(file):
    """
    Checks if the magic matches.
    :param file: a string or readable binary stream
    :return: bool
    """

    if isinstance(file, str):
        with open(file, 'rb') as file:
            return file.read(len(MAGIC)) == MAGIC
    elif hasattr(file, 'read') and file.readable():
        return file.read(len(MAGIC)) == MAGIC
    raise ValueError('Invalid argument for arg file, expected a string or a readable stream.')


class SizeMode(enum.IntEnum):
    m16 = 0
    m32 = 1
    m64 = 2


@dataclasses.dataclass
class FileInfo:
    name: str
    size: int
    crc: int
    offset: int  # offset to header
    data_offset: int  # offset to data


class StaticArchive:
    def __init__(self, file, mode: str = 'r',
                 size_mode: SizeMode = SizeMode.m64,
                 write_crc: bool = True,
                 checks: bool = True):

        assert mode in ('a', 'w', 'r'), 'mode must be "a", "w" or "r"'

        self._mode = mode
        self._size_mode = size_mode
        self._crc = write_crc
        self._closed = False
        self.checks = checks  # rw

        if isinstance(file, str):
            fm = {
                'a': 'rb+',
                'w': 'wb+',
                'r': 'rb',
            }[mode]
            self._stream = open(file, fm)
        elif isinstance(file, io.IOBase):
            assert file.readable(), 'stream must be readable'
            assert file.seekable(), 'stream must be seekable'
            assert not file.closed, 'stream cannot be closed'

            if mode != 'r':
                assert file.writable(), 'stream must be writeable for mode %s' % mode

            self._stream = file
        else:
            raise ValueError('Invalid argument for file %s, expected a string or a binary stream' % str(file))

        self._start_offset = self._stream.tell()
        self._file_count = 0
        self.general_purpose_field = 0

        if self._mode in ('r', 'a'):
            if self.checks:
                assert self._check_sig(), 'Invalid file signature'
            self._load_sig()
        else:
            self._write_sig()

    # signature
    @_lock
    def _check_sig(self):
        self._stream.seek(self._start_offset)
        magic = self._stream.read(len(MAGIC))
        return MAGIC == magic

    @_lock
    def _load_sig(self):
        if self.checks:
            assert self._check_sig()
        self._stream.seek(self._start_offset + len(MAGIC))
        self.general_purpose_field = _decode(self._stream.read(DWORD))
        self._file_count = _decode(self._stream.read(QWORD))
        self._size_mode = self._stream.read(BYTE)[0]
        self._crc = bool(self._stream.read(BYTE)[0])

    @_lock
    def _write_sig(self):
        self._stream.seek(self._start_offset)
        self._stream.write(MAGIC)
        self._stream.write(_encode(self.general_purpose_field, DWORD))
        self._stream.write(_encode(self._file_count, QWORD))
        self._stream.write(_encode(self._size_mode, BYTE))
        self._stream.write(_encode(self._crc, BYTE))

    # entry header
    def _read_hdr(self):
        ns = self._stream.read(BYTE)[0]
        name = self._stream.read(ns).decode(ENCODING)

        crc = None
        if self._crc:
            crc = _decode(self._stream.read(DWORD))

        ds = _decode(self._stream.read(CONV_MODE[self._size_mode]))
        return name, crc, ds

    def _write_hdr(self, name, crc, ds):
        self._stream.write(_encode(len(name), BYTE))
        self._stream.write(name.encode(ENCODING))

        if self._crc:
            self._stream.write(_encode(crc, DWORD))

        self._stream.write(_encode(ds, CONV_MODE[self._size_mode]))

    def append(self, name: str, data: Union[bytes, BinaryIO]) -> FileInfo:
        """
        Append a file onto the archive
        :param name: filename
        :param data: stream or raw data
        :return: FileInfo
        """
        if self._mode == 'r':
            raise TypeError('Cannot append to a read-only archive')

        # assuming EOF is at the end of the stacked entries
        offset = self._stream.seek(0, 2)
        if not hasattr(data, 'read'):
            data = io.BytesIO(data)

        p = data.tell()
        ds = data.seek(0, 2)
        data.seek(p)
        ds -= p

        self._write_hdr(name, 0, ds)
        p = self._stream.tell()

        crc_cb = None
        last_csum = 0
        if self._crc:
            def crc_cb(chunk):
                nonlocal last_csum
                last_csum = zlib.crc32(chunk, last_csum)

        count = _move_stream(data, self._stream, BUFFER_SIZE, fn=crc_cb)
        assert count == ds

        if self._crc:
            self._stream.seek(p - (DWORD + QWORD))
            self._stream.write(_encode(last_csum, DWORD))
        self._file_count += 1

        return FileInfo(name, ds, last_csum, offset, p)

    def read(self, file: Union[FileInfo, str]) -> bytes:
        """ Read a file from the archive with a name or FileInfo. """
        buffer = io.BytesIO()
        self.read_into(file, buffer)
        return buffer.getvalue()

    def read_into(self, file: Union[FileInfo, str], dest: BinaryIO) -> int:
        """ Read the contents of a file inside the archive into another stream. """
        if isinstance(file, str):
            file = self.file_info(file)

        self._stream.seek(file.offset)
        name, crc, ds = self._read_hdr()
        last_csum = 0

        def crc_cb(chunk):
            nonlocal last_csum
            last_csum = zlib.crc32(chunk, last_csum)

        res = _move_stream(self._stream, dest, BUFFER_SIZE, ds, fn=crc_cb)
        assert res == ds

        if self.checks:
            assert crc == last_csum

        return res

    # fs methods
    @staticmethod
    def _bar(i, total, ts):
        percent = (i / total) * 100
        bar_count = round(percent * (ts / 100))
        print(
            f'\r[{"#" * bar_count}{"." * (ts - bar_count)}] ',
            '%.2f' % percent,
            f'% {str(i).ljust(4, " ")}/{total}',
            sep='', end=''
        )


    def add(self, path: str, verbose=False, only_names=False, ignore=False) -> List[FileInfo]:
        """
        Add a directory or a single file into the archive recursively.
        """
        appended_files = list()
        target_files = list()

        is_file = isfile(path)

        if is_file:
            target_files.append(path)
        elif isdir(path):
            def trace_dir(pth):
                nonlocal target_files

                for file in os.scandir(pth):
                    if file.is_file():
                        target_files.append(file.path)
                    elif file.is_dir():
                        trace_dir(file.path)

            trace_dir(path)

        ts = shutil.get_terminal_size((40, 40)).columns // 2
        for i, target in enumerate(target_files):
            if verbose:
                self._bar(i, len(target_files), ts)

            if only_names:
                name = os.path.basename(target)
            else:
                if is_file:
                    name = target
                else:
                    name = os.path.relpath(target, path)

            try:
                with open(target, 'rb') as f:
                    appended_files.append(self.append(name, f))
            except Exception as e:
                if verbose:
                    print('\r Error while appending file %s "%s"' % (target, f'{type(e).__name__}{e.args}'))
                if not ignore:
                    raise
        if verbose:
            print('\r')

        return appended_files

    def extract(self, path: str, names: list = None, verbose=False):
        if not isdir(path):
            raise FileNotFoundError('%s does not exist or is not a directory' % path)

        if names is not None:
            _infos = tuple(self.file_infos())

            def _(x):
                if isinstance(x, FileInfo):
                    return x

                elif isinstance(x, str):
                    try:
                        return list(filter(lambda y: y.name == x, _infos))[0]
                    except IndexError:
                        raise ValueError('%s is not a file contained by the archive' % x)

            scheduled_files = tuple(map(_, names))
        else:
            scheduled_files = tuple(self.file_infos())

        ts = shutil.get_terminal_size((40, 40)).columns // 2
        for i, file in enumerate(scheduled_files):
            if verbose:
                self._bar(i, len(scheduled_files), ts)

            fp = join(path, file.name)
            os.makedirs(split(fp)[0], exist_ok=True)

            with open(fp, 'wb') as f:
                self.read_into(file, f)

        print('\r')

    def file_info(self, name: str) -> FileInfo:
        """
        Retrieve the FileInfo for the given name.
        NOTE: This is an expensive call.
        """
        try:
            return tuple(filter(lambda x: x.name == name, self.file_infos()))[0]
        except IndexError:
            raise ValueError('%s is not contained inside the archive' % name)

    def file_infos(self) -> Generator:
        """ Retrieve FileInfos for all files inside the archive. """
        self._stream.seek(self._start_offset + READ_OFFSET)

        for i in range(self._file_count):
            offset = self._stream.tell()
            name, crc, ds = self._read_hdr()
            data_offset = self._stream.tell()
            self._stream.seek(ds, 1)

            yield FileInfo(name, ds, crc, offset, data_offset)

    def file_names(self) -> Generator:
        """ Retrieve all filenames for all files inside the archive. """
        for info in self.file_infos():
            yield info.name

    @staticmethod
    def readable() -> bool:
        """ Is the archive readable? (Yes, always.) """
        return True

    def writeable(self) -> bool:
        """ Is the archive writeable? """
        return self._mode != 'r'

    def flush(self):
        """ Flush all in memory data to disk. """
        if self._mode != 'r':
            self._write_sig()

    def close(self):
        """ Flushes and closes the underlying stream. """
        self.flush()
        if not self._stream.closed:
            self._stream.close()
        self._closed = True

    @property
    def mode(self):
        """ The mode the archive is opened in. """
        return self._mode

    @property
    def closed(self):
        """ Whether the archive and the underlying stream is closed. """
        return self._closed

    @property
    def size_mode(self):
        """ Specifies the max file size """
        return self._size_mode

    @property
    def crc(self):
        """ Whether a checksum is used inside the archive. """
        return self._crc

    @property
    def file_count(self):
        """ The amount of files stored inside this archive. """
        return self._file_count

    @property
    def max_filesize(self):
        """ The maximum filesize for any file in the archive. """
        return [
            0xFFFF,
            0xFFFF_FFFF,
            0xFFFF_FFFF_FFFF_FFFF
        ][self._size_mode]

    def __enter__(self):
        assert not self._closed, 'cannot enter closed file'
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    args = parse_args()

    if args.M16:
        mode = SizeMode.m16
    elif args.M32:
        mode = SizeMode.m32
    elif args.M64:
        mode = SizeMode.m64
    else:
        mode = SizeMode.m64

    cmd = args.cmd.lower()
    if cmd not in ('list', 'l') and args.src is None:
        print('the source argument is required for command', args.cmd)
        return 1

    if cmd in ('create', 'c'):
        with StaticArchive(
            args.file, 'w',
            size_mode=mode,
            write_crc=args.crc,
            checks=args.checks
        ) as sa:
            sa.add(
                args.src,
                verbose=args.verbose,
                only_names=args.names,
            )

    elif cmd in ('append', 'a'):
        with StaticArchive(
            args.file, 'a',
            size_mode=mode,
            write_crc=args.crc,
            checks=args.checks
        ) as sa:
            sa.add(
                args.src,
                verbose=args.verbose,
                only_names=args.names,
            )

    elif cmd in ('extract', 'e'):
        with StaticArchive(
            args.file, 'r',
            size_mode=mode,
            write_crc=args.crc,
            checks=args.checks,
        ) as sa:
            sa.extract(
                args.src,
                verbose=args.verbose,
                names=args.limit,
            )

    elif cmd in ('list', 'l'):
        with StaticArchive(
            args.file, 'r',
            size_mode=mode,
            write_crc=args.crc,
            checks=args.checks,
        ) as sa:
            print(
                '--- STATIC ARCHIVE ---',
                'Size Mode: %s' % SizeMode(sa.size_mode).name,
                'General Purpose Number: %i' % sa.general_purpose_field,
                'CRC32: %s' % {True: 'used', False: 'not used'}[sa.crc],
                'File Count: %i' % sa.file_count,
                'Maximal Filesize: %i' % sa.max_filesize,
                '---',
                'Files Contained:',
                *sa.file_names(),
                sep='\n', end='\n',
            )
    else:
        print('Unknown command', args.cmd)
        return 1
    return 0


if __name__ == '__main__':
    exit(main())
