cmake_minimum_required(VERSION 3.22.1)
project(yolsec C)
add_library(yolsec SHARED sec.c)
target_include_directories(yolsec PRIVATE ${SEC_DIR})
target_compile_options(yolsec PRIVATE -O2 -fvisibility=hidden -fno-asynchronous-unwind-tables -fno-unwind-tables)
target_link_options(yolsec PRIVATE -s -Wl,--gc-sections -Wl,-z,noexecstack)
target_link_libraries(yolsec PRIVATE dl)
# 1.47.16: möhür — derlenen kitaphananyň ýerine ýetirilýän bölegi SEAL-a ýazylýar (python3 hökmany)
find_program(PY3 python3 REQUIRED)
add_custom_command(TARGET yolsec POST_BUILD
    COMMAND ${PY3} ${CMAKE_CURRENT_SOURCE_DIR}/seal.py $<TARGET_FILE:yolsec> ${SEC_DIR}/seal.txt
    VERBATIM)
