cmake_minimum_required(VERSION 3.22)
project(StaticArchive)

set(CMAKE_CXX_STANDARD 17)

find_package(ZLIB REQUIRED)
find_package(CxxTest)

# core targets
add_library(core OBJECT src/core/static.cpp)
target_link_libraries(core ZLIB::ZLIB)

add_library(static SHARED $<TARGET_OBJECTS:core> src/lib_main.cpp)
add_executable(static_exe $<TARGET_OBJECTS:core> src/main.cpp)


if(CXXTEST_FOUND)
    include_directories(${CXXTEST_INCLUDE_DIR})
    enable_testing()
    set(TEST_FILES src/tests/testSuite1.h++)
    CXXTEST_ADD_TEST(tests
        ${TEST_FILES}
    )
    # add_executable(test_exe $<TARGET_OBJECTS:core> src/test_runner.cpp)
endif()

