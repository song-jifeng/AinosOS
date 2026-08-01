#ifndef POLICY_DB_H
#define POLICY_DB_H

#include "ainos/ai_policy.h"

int pdb_init(const char *db_path);
void pdb_destroy(void);
int pdb_save_apl_text(const char *profile_name, const char *apl_text);
int pdb_load_apl_text(const char *profile_name, char **out_text);
int pdb_import_apl_file(const char *filepath);
int pdb_export_apl_file(const char *profile_name, const char *filepath);
int pdb_get_version(int *version);
int pdb_bump_version(void);

#endif