
#ifndef CPP_STATIC_HPP
#define CPP_STATIC_HPP

#include <iostream>
#include <tuple>
#include <memory>
#include <vector>

#define STATIC_FLAG_VERBOSE        0b10000000
#define STATIC_FLAG_ONLY_NAMES     0b01000000
#define STATIC_FLAG_IGNORE_ERRORS  0b00100000
#define STATIC_FLAG_WRITE_CRC32    0b00010000
#define STATIC_FLAG_DISABLE_CHECKS 0b00001000


#define STATIC_MAGIC { 0x91, 0xde, 0xee, 0x9c, 0x80, 0x5c, 0x23, 0xe6 };

namespace Static {

    enum SizeMode {
        SizeMode16,
        SizeMode32,
        SizeMode64,
    };

    enum Mode {
        ModeRead,
        ModeAppend,
        ModeCreate,
    };

    struct FileInfo {
        const char *name;
        uint64_t size;
        uint32_t crc;
        uint64_t offset;
        uint64_t dataOffset;
    };

    struct EntryHeader {
        std::string name;
        uint32_t crc;
        uint64_t dataSize;
    };

    union Flags{
        struct FlagsStruct{
            uint8_t verbose : 1;
            uint8_t onlyNames : 1;
            uint8_t ignoreErrors : 1;
            uint8_t writeCrc : 1;
            uint8_t checks : 1;
        } f;
        uint8_t v;
    };

    bool is_archive(const char *path);

    class StaticArchive {
    public:
        explicit StaticArchive(const std::string& path);
        StaticArchive(const std::string& path, Mode mode);
        StaticArchive(const std::string& path, Mode mode, SizeMode sizeMode);
        StaticArchive(const std::string& path, Mode mode, SizeMode sizeMode, uint8_t flags);
        StaticArchive(std::fstream *stream, Mode mode, SizeMode sizeMode, uint8_t flags);

        template<typename T>
        FileInfo append(const std::string &name, T *data);
        FileInfo append(const std::string &name, std::basic_ios<uint8_t>& stream);

        template<typename T>
        uint64_t read(FileInfo file, T* out);

        template<typename T>
        uint64_t read(FileInfo file, std::vector<T>& out);
        uint64_t read(FileInfo file, std::string& out);
        uint64_t read(FileInfo file, std::basic_ios<uint8_t>& stream);

        std::vector<FileInfo> add(std::string path, uint8_t flags = 0);
        void extract(std::string path, uint8_t flags = 0);
        void extract(std::string path, std::vector<FileInfo>& names, uint8_t flags = 0);

        FileInfo getFileInfo(std::string name);
        void getFileInfos(std::vector<FileInfo>& out);
        void getFileNames(std::vector<std::string>& out);

        bool isReadable();
        bool isWriteable();

        void flush();
        void close();

        [[nodiscard]] SizeMode getSizeMode() const noexcept;
        [[nodiscard]] uint64_t getFileCount() const noexcept;
        [[nodiscard]] uint64_t getMaxFilesize() const noexcept;
        [[nodiscard]] bool getWriteCrc() const noexcept;
        [[nodiscard]] bool getClosed() const noexcept;
        [[nodiscard]] Mode getMode() const noexcept;

        uint32_t generalPurposeField;
        bool checks;
    private:
        inline void setup(const std::string& path, const Mode& mode_, const SizeMode& sizeMode_);
        bool checkSignature();
        void loadSignature();
        void writeSignature();
        EntryHeader readHeader();
        void writeheader(std::string &name, uint32_t crc, uint64_t dataSize);

        std::fstream *stream;
        SizeMode sizeMode = SizeMode64;
        Mode mode = ModeRead;
        uint64_t fileCount = 0;
        bool writeCrc = true;
        bool closed = false;

        ~StaticArchive();
    };

    // Exceptions
    class InvalidNameSizeException : public std::exception {
    public:
        explicit InvalidNameSizeException(uint64_t size) {
            this->size = size;
        }

        virtual const char* what() const throw() {
            return "Invalid name field size";
        }

        uint64_t size;
    };
}

#endif //CPP_STATIC_HPP
