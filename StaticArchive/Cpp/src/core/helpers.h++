
#ifndef STATICARCHIVE_HELPERS_H
#define STATICARCHIVE_HELPERS_H

#define BYTE 1
#define WORD 2
#define DWORD 4
#define QWORD 8


template <typename T>
union conv {
    T value;
    uint8_t data[sizeof(T)];
};



#endif //STATICARCHIVE_HELPERS_H
