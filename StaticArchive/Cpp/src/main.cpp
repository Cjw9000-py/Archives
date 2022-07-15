#include <memory>
#include <sstream>
#include <streambuf>
#include <iostream>
#include <zlib.h>



int main() {
    char data[1000]{};

    uint32_t res = crc32(0, reinterpret_cast<const Bytef *>(&data), 1000);
    std::cout << res << "\n";
}