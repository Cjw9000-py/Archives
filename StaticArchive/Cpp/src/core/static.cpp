
#include "static.h++"
#include "static.h"
#include "helpers.h++"

#include <fstream>
#include <cstring>

using namespace Static;



// C functions and root level functions
bool Static::is_archive(const char *path) {

}

// Public methods
StaticArchive::StaticArchive(const std::string &path) {
    setup(path, ModeRead, SizeMode64);
}

StaticArchive::StaticArchive(const std::string &path, Mode mode) {
    setup(path, mode, SizeMode64);
}

StaticArchive::StaticArchive(const std::string &path, Mode mode, SizeMode sizeMode) {
    setup(path, mode, sizeMode);
}

StaticArchive::StaticArchive(const std::string &path, Mode mode, SizeMode sizeMode, uint8_t flags) {
    setup(path, mode, sizeMode);

    Flags flags_{flags};
    checks = flags_.f.checks;
    writeCrc = flags_.f.writeCrc;
}

StaticArchive::StaticArchive(std::fstream *stream, Mode mode, SizeMode sizeMode, uint8_t flags) {
    this->mode = mode;
    this->stream = stream;
    this->sizeMode = sizeMode;

    Flags flags_{flags};
    checks = flags_.f.checks;
    writeCrc = flags_.f.writeCrc;
}

template<typename T>
FileInfo StaticArchive::append(const std::string &name, T *data) {}
FileInfo StaticArchive::append(const std::string &name, std::basic_ios<uint8_t> &stream) {}

// Private Methods
inline void StaticArchive::setup(const std::string &path, const Mode &mode_, const SizeMode &sizeMode_) {
    stream = new std::fstream(path, std::fstream::binary | std::fstream::in | std::fstream::out);

    mode = mode_;
    sizeMode = sizeMode_;
}

bool StaticArchive::checkSignature() {
    stream->seekg(0);

    uint8_t magic[QWORD] = STATIC_MAGIC;
    uint8_t buffer[QWORD];

    stream->read((char*)&buffer, QWORD);
    return strncmp((char*)&magic, (char*)&buffer, QWORD);
}

void StaticArchive::loadSignature() {
    stream->seekg(QWORD);

    conv<uint32_t> gp{};
    stream->read((char*)gp.data, DWORD);
    generalPurposeField = gp.value;

    conv<uint64_t> fc{};
    stream->read((char*)gp.data, QWORD);
    fileCount = fc.value;

    sizeMode = (SizeMode)stream->get();
    writeCrc = (bool)stream->get();
}

void StaticArchive::writeSignature() {
    stream->seekp(0);

    uint8_t magic[QWORD] = STATIC_MAGIC;
    stream->write((char*)&magic, QWORD);

    conv<uint32_t> gp{generalPurposeField};
    stream->write((char*)gp.data, DWORD);

    conv<uint64_t> fc{fileCount};
    stream->write((char*)fc.data, QWORD);

    stream->put((char)sizeMode);
    stream->put((char)writeCrc);
}

EntryHeader StaticArchive::readHeader() {
    uint8_t ns = stream->get();
    char* nameBuffer = new char[ns];
    stream->read(nameBuffer, ns);
    std::string name = nameBuffer;
    delete[] nameBuffer;

    conv<uint32_t> crc{};
    stream->read((char*)&crc.data, DWORD);

    uint64_t dataSize;
    switch (sizeMode) {
        case SizeMode64:
        {
            conv<uint64_t> ds{};
            stream->read((char*)&ds.data, QWORD);
            dataSize = ds.value;
            break;
        }
        case SizeMode32:
        {
            conv<uint32_t> ds{};
            stream->read((char*)&ds.data, DWORD);
            dataSize = ds.value;
            break;
        }
        case SizeMode16:
        {
            conv<uint16_t> ds{};
            dataSize = ds.value;
            stream->read((char*)&ds.data, WORD);
            break;
        }
    }

    EntryHeader hdr{std::move(name), crc.value, dataSize};
    return hdr;
}

void StaticArchive::writeheader(std::string &name, uint32_t crc, uint64_t dataSize) noexcept(false) {
    if (name.size() > 256)
        throw InvalidNameSizeException(name.size());

    stream->put((char)name.size());
    stream->write(name.c_str(), (int64_t)name.size());

    conv<uint32_t> crc_conv{crc};
    stream->write((char*)&crc_conv.data, DWORD);

    conv<uint64_t> ds{dataSize};
    stream->write((char*)&ds.data, QWORD);
}

StaticArchive::~StaticArchive() {
    if (stream->is_open())
        stream->close();
    delete stream;
}


// Properties
SizeMode StaticArchive::getSizeMode() const noexcept { return sizeMode; }

uint64_t StaticArchive::getFileCount() const noexcept { return fileCount; }

bool StaticArchive::getWriteCrc() const noexcept { return writeCrc; }

bool StaticArchive::getClosed() const noexcept { return closed; }

Mode StaticArchive::getMode() const noexcept { return mode; }

uint64_t StaticArchive::getMaxFilesize() const noexcept {
    switch (sizeMode) {
        case SizeMode16:
            return 0xffff;
        case SizeMode32:
            //       |--||--|
            return 0xffffffff;
        case SizeMode64:
            //       |--||--||--||--|
            return 0xffffffffffffffff;
    }
    return 0;
}