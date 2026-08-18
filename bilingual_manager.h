#ifndef BILINGUAL_MANAGER_H
#define BILINGUAL_MANAGER_H

#include <string>
#include <vector>
#include <map>
#include <tuple>

class Usecode_machine;

enum class TextLanguage { ENGLISH = 0, CHINESE = 1, DUAL = 2 };

struct VoiceMapping {
    int zh_func_id;
    std::string zh_offset_key;
    int zh_segment;
    int en_func_id;
    std::string en_offset_key;
    int en_segment;
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
                    const std::string& offset_key, int segment,
                    int& out_func_id, std::string& out_offset_key,
                    int& out_segment);

    bool is_bilingual_available() const { return usecode_zh != nullptr; }
    bool is_dual_available() const { return usecode_dual != nullptr; }
    // True when the current text mode renders Chinese (ZH or DUAL).
    bool is_zh_text() const {
        return current_lang == TextLanguage::CHINESE
               || current_lang == TextLanguage::DUAL;
    }
    // Language used for non-dialogue UI lookups (spell names etc.):
    // DUAL behaves as CHINESE.
    TextLanguage script_language() const {
        return (current_lang == TextLanguage::DUAL) ? TextLanguage::CHINESE
                                                    : current_lang;
    }

private:
    BilingualManager() = default;
    void load_usecode_files();
    void load_map_file(const std::string& path, std::vector<VoiceMapping>& out);
    void load_bilingual_map();

    TextLanguage current_lang = TextLanguage::ENGLISH;
    Usecode_machine* usecode_en = nullptr;
    Usecode_machine* usecode_zh = nullptr;
    Usecode_machine* usecode_dual = nullptr;
    std::vector<VoiceMapping> dual_map;    // dual->zh / dual->en rows (BLM2)
    std::vector<VoiceMapping> bilingual_map;
};

#endif
