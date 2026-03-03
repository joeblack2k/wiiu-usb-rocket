cmake_minimum_required(VERSION 3.20)

project(wfs_core_native)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(WFSLIB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/wfslib)

add_subdirectory(${WFSLIB_DIR} ${CMAKE_CURRENT_BINARY_DIR}/wfslib-build)

find_package(pybind11 REQUIRED)

pybind11_add_module(wfs_core_native
  src/bindings.cpp
  src/wfs_core_engine.cpp
)

target_include_directories(wfs_core_native
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${WFSLIB_DIR}/src
)

target_link_libraries(wfs_core_native
  PRIVATE
    wfslib
)
