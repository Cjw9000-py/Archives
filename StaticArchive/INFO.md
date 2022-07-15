# Static Archive

This is an archive, that is very similar to the gnu tar-archive. \
It aims to be fast and produce small (archive) file sizes, at large file count.

Its usage cases could be:
- embedding files into binaries
- storing datasets for machine learning

Currently, it does not support
- compression (except you compress the complete archive)
- encryption ( -- )

There are 3 modes
- 16 bit Mode
- 32 bit Mode
- 64 bit Mode

The modes describe the maximal size of a file that can be contained by the archive.
- 16 bit -> `65535 bytes`
- 32 bit -> `4294967295 bytes`
- 64 bit -> `18446744073709551615 bytes`

It includes a CRC32 for each file. But this feature can be turned off, for improvements in 
1. speed
2. archive file size

---

### static.bt

´static.bt´
Is a template for the 010 hexeditor. \
Link [https://www.sweetscape.com/010editor/](https://www.sweetscape.com/010editor/).