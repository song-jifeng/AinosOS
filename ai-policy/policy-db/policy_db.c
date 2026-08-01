#include "policy_db.h"
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static sqlite3 *db = NULL;

int pdb_init(const char *db_path) {
    if (sqlite3_open(db_path, &db) != SQLITE_OK) return -1;
    
    const char *sql = 
        "CREATE TABLE IF NOT EXISTS profiles ("
        "id INTEGER PRIMARY KEY, name TEXT UNIQUE, apl_text TEXT);"
        "CREATE TABLE IF NOT EXISTS metadata ("
        "key TEXT PRIMARY KEY, value TEXT);";
        
    char *err = NULL;
    if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
        sqlite3_free(err);
        return -1;
    }
    return 0;
}

void pdb_destroy(void) {
    if (db) sqlite3_close(db);
    db = NULL;
}

int pdb_save_apl_text(const char *profile_name, const char *apl_text) {
    const char *sql = "INSERT OR REPLACE INTO profiles (name, apl_text) VALUES (?, ?);";
    sqlite3_stmt *stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) return -1;
    
    sqlite3_bind_text(stmt, 1, profile_name, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, apl_text, -1, SQLITE_STATIC);
    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return (rc == SQLITE_DONE) ? 0 : -1;
}

int pdb_load_apl_text(const char *profile_name, char **out_text) {
    const char *sql = "SELECT apl_text FROM profiles WHERE name = ?;";
    sqlite3_stmt *stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) return -1;
    
    sqlite3_bind_text(stmt, 1, profile_name, -1, SQLITE_STATIC);
    int rc = sqlite3_step(stmt);
    if (rc == SQLITE_ROW) {
        const char *text = (const char *)sqlite3_column_text(stmt, 0);
        *out_text = strdup(text);
        sqlite3_finalize(stmt);
        return 0;
    }
    sqlite3_finalize(stmt);
    return -1;
}

int pdb_bump_version(void) {
    const char *sql = "INSERT OR REPLACE INTO metadata (key, value) VALUES ('version', "
                      "COALESCE((SELECT CAST(value AS INTEGER) + 1 FROM metadata WHERE key='version'), '1'));";
    char *err = NULL;
    return (sqlite3_exec(db, sql, NULL, NULL, &err) == SQLITE_OK) ? 0 : -1;
}