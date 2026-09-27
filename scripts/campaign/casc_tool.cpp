// Read files from the local StarCraft II CASC storage (read-only).
//   casc_tool list <game dir> <mask>          prints "name<TAB>size" per file
//   casc_tool extract <game dir>               reads "name<TAB>output path" lines on stdin
#include "CascLib.h"
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static bool extract(HANDLE storage, const std::string& name, const std::string& out_path) {
    HANDLE file = NULL;
    if (!CascOpenFile(storage, name.c_str(), 0, CASC_OPEN_BY_NAME, &file)) return false;
    FILE* out = fopen(out_path.c_str(), "wb");
    if (!out) { CascCloseFile(file); return false; }
    std::vector<char> buffer(1 << 20);
    DWORD read = 0;
    while (CascReadFile(file, buffer.data(), (DWORD)buffer.size(), &read) && read) fwrite(buffer.data(), 1, read, out);
    fclose(out);
    CascCloseFile(file);
    return true;
}

int main(int argc, char** argv) {
    if (argc < 3) { fprintf(stderr, "usage: casc_tool list <dir> <mask> | extract <dir>\n"); return 2; }
    HANDLE storage = NULL;
    if (!CascOpenStorage(argv[2], 0, &storage)) { fprintf(stderr, "cannot open storage: %d\n", GetCascError()); return 1; }
    int failures = 0;
    if (!strcmp(argv[1], "list") && argc >= 4) {
        CASC_FIND_DATA found;
        HANDLE find = CascFindFirstFile(storage, argv[3], &found, NULL);
        if (find == NULL || find == INVALID_HANDLE_VALUE) { fprintf(stderr, "find failed: %d\n", GetCascError()); return 1; }
        do { printf("%s\t%llu\n", found.szFileName, (unsigned long long)found.FileSize); } while (CascFindNextFile(find, &found));
        CascFindClose(find);
    } else if (!strcmp(argv[1], "extract")) {
        char line[4096];
        while (fgets(line, sizeof line, stdin)) {
            line[strcspn(line, "\r\n")] = 0;
            char* tab = strchr(line, '\t');
            if (!tab) continue;
            *tab = 0;
            if (!extract(storage, line, tab + 1)) { fprintf(stderr, "failed: %s\n", line); failures++; }
        }
    }
    CascCloseStorage(storage);
    return failures ? 1 : 0;
}
