#include "bilingual_manager.h"
#include "usecode/ucmachine.h"
#include "gamewin.h"
#include "singles.h"
#include "fnames.h"
#include "utils.h"
#include "Configuration.h"
#include <iostream>

BilingualManager& BilingualManager::get() {
    static BilingualManager instance;
    return instance;
}

void BilingualManager::init() {
    std::string text_lang_str, voice_lang_str;
    config->value("config/audio/text/language", text_lang_str, "en");
    config->value("config/audio/voice/language", voice_lang_str, "zh");

    current_lang = (text_lang_str == "zh") ? TextLanguage::CHINESE : TextLanguage::ENGLISH;

    load_usecode_files();
    load_bilingual_map();

    std::cout << "[Bilingual] Text language: "
              << (current_lang == TextLanguage::CHINESE ? "zh" : "en") << std::endl;
    std::cout << "[Bilingual] Voice language: " << voice_lang_str << std::endl;
    std::cout << "[Bilingual] Bilingual mode: "
              << (is_bilingual_available() ? "yes" : "no") << std::endl;
}

void BilingualManager::shutdown() {
    delete usecode_zh;
    usecode_zh = nullptr;
}

void BilingualManager::load_usecode_files() {
    Game_window* gwin = Game_window::get_instance();
    if (gwin) {
        usecode_en = gwin->get_usecode();
    }

    if (is_system_path_defined("<PATCH>") && U7exists(ZH_USECODE)) {
        try {
            auto pFile = U7open_in(ZH_USECODE);
            if (pFile) {
                usecode_zh = Usecode_machine::create();
                usecode_zh->read_usecode(*pFile);
            }
        } catch (const std::exception& e) {
            std::cerr << "[Bilingual] Failed to load Chinese usecode: "
                      << e.what() << std::endl;
            usecode_zh = nullptr;
        }
    }
}

void BilingualManager::load_bilingual_map() {
}

void BilingualManager::set_text_language(TextLanguage lang) {
    if (lang == current_lang) return;
    current_lang = lang;

    Game_window* gwin = Game_window::get_instance();
    if (gwin) {
        gwin->usecode = get_active_usecode();
        Game_singletons::init(gwin);
        gwin->set_all_dirty();
    }
}

Usecode_machine* BilingualManager::get_active_usecode() {
    return (current_lang == TextLanguage::CHINESE && usecode_zh)
           ? usecode_zh : usecode_en;
}

Usecode_machine* BilingualManager::get_usecode(TextLanguage lang) {
    return (lang == TextLanguage::CHINESE) ? usecode_zh : usecode_en;
}

bool BilingualManager::map_offset(TextLanguage from_lang, int func_id,
                                   const std::string& offset_key,
                                   int& out_func_id, std::string& out_offset_key) {
    return false;
}
