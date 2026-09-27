// Pack a directory of map components into an MPQ archive (.SC2Map): mpq_pack <out.SC2Map> <dir>
#include "StormLib.h"
#include <cstdio>
#include <filesystem>
#include <string>
namespace fs = std::filesystem;

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: mpq_pack <out.SC2Map> <dir>\n"); return 2; }
    fs::path root(argv[2]);
    int count = 0;
    for (auto& entry : fs::recursive_directory_iterator(root)) if (entry.is_regular_file()) count++;
    fs::remove(argv[1]);
    HANDLE archive = NULL;
    if (!SFileCreateArchive(argv[1], MPQ_CREATE_ARCHIVE_V3 | MPQ_CREATE_LISTFILE | MPQ_CREATE_ATTRIBUTES,
                            count + 16, &archive)) {
        fprintf(stderr, "cannot create archive: %d\n", SErrGetLastError()); return 1;
    }
    for (auto& entry : fs::recursive_directory_iterator(root)) {
        if (!entry.is_regular_file()) continue;
        std::string name = fs::relative(entry.path(), root).string();
        for (auto& c : name) if (c == '/') c = '\\';
        if (!SFileAddFileEx(archive, entry.path().c_str(), name.c_str(), MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING,
                            MPQ_COMPRESSION_ZLIB, MPQ_COMPRESSION_NEXT_SAME)) {
            fprintf(stderr, "cannot add %s: %d\n", name.c_str(), SErrGetLastError()); return 1;
        }
    }
    SFileCloseArchive(archive);
    return 0;
}
