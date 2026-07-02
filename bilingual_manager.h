#ifndef BILINGUAL_MANAGER_H
#define BILINGUAL_MANAGER_H

#include <string>
#include <vector>
#include <map>
#include <tuple>

class Usecode_machine;

enum class TextLanguage { ENGLISH = 0, CHINESE = 1 };

struct VoiceMapping {
    int zh_func_id;
    std::string zh_offset_key;
    int segment;
    int en_func_id;
    std::string en_offset_key;
};

class BilingualManager {
public:
    static BilingualManager& get();

    void init();
    void shutdown();

    TextLanguage get_text_language() const { return current_lang; }
    void set_text_language(TextLanguage lang);

    Usecode_machine* get_active_usecode();
    Usecode_machine* get_usecode(TextLanguage lang);

    bool map_offset(TextLanguage from_lang, int func_id,
                    const std::string& offset_key,
                    int& out_func_id, std::string& out_offset_key);

    bool is_bilingual_available() const { return usecode_zh != nullptr; }

private:
    BilingualManager() = default;
    void load_usecode_files();
    void load_bilingual_map();

    TextLanguage current_lang = TextLanguage::ENGLISH;
    Usecode_machine* usecode_en = nullptr;
    Usecode_machine* usecode_zh = nullptr;
    std::vector<VoiceMapping> bilingual_map;
};

#endif
