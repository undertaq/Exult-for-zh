#include "bilingual_manager.h"
#include "usecode/ucmachine.h"
#include "gamewin.h"
#include "items.h"
#include "singles.h"
#include "fnames.h"
#include "utils.h"
#include "Configuration.h"
#include <cstring>
#include <iostream>

BilingualManager& BilingualManager::get() {
    static BilingualManager instance;
    return instance;
}

void BilingualManager::init() {
    std::string text_lang_str, voice_lang_str;
    config->value("config/audio/text/language", text_lang_str, "en");
    config->value("config/audio/speech/voice/language", voice_lang_str, "zh");
    // Write text language default back so config always has the key
    config->set("config/audio/text/language", text_lang_str, false);

    current_lang = (text_lang_str == "zh")   ? TextLanguage::CHINESE
                   : (text_lang_str == "dual") ? TextLanguage::DUAL
                                               : TextLanguage::ENGLISH;

    load_usecode_files();
    load_bilingual_map();

    Game_window* gwin = Game_window::get_instance();
    if (gwin) {
        gwin->set_usecode(get_usecode(current_lang));
        Game_singletons::init(gwin);
    }

    std::cout << "[Bilingual] Text language: "
              << (current_lang == TextLanguage::CHINESE ? "zh" : "en") << std::endl;
    std::cout << "[Bilingual] Voice language: " << voice_lang_str << std::endl;
    std::cout << "[Bilingual] Bilingual mode: "
              << (is_bilingual_available() ? "yes" : "no") << std::endl;
}

void BilingualManager::shutdown() {
    delete usecode_zh;
    usecode_zh = nullptr;
    delete usecode_dual;
    usecode_dual = nullptr;
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

    if (is_system_path_defined("<PATCH>")) {
        if (U7exists(DUAL_USECODE)) {
            try {
                auto pFile = U7open_in(DUAL_USECODE);
                if (pFile) {
                    usecode_dual = Usecode_machine::create();
                    usecode_dual->read_usecode(*pFile);
                }
            } catch (const std::exception& e) {
                std::cerr << "[Bilingual] Failed to load dual usecode: "
                          << e.what() << std::endl;
                usecode_dual = nullptr;
            }
        } else {
            std::cout << "[Bilingual] usecode.dual not found; "
                         "dual mode will fall back to Chinese" << std::endl;
        }
    }
}

void BilingualManager::load_map_file(const std::string& map_path,
                                     std::vector<VoiceMapping>& out) {
    out.clear();

    if (!is_system_path_defined("<PATCH>")) {
        return;
    }

    if (!U7exists(map_path)) {
        std::cout << "[Bilingual] No voice map found at " << map_path << std::endl;
        return;
    }

    try {
        auto pFile = U7open_in(map_path.c_str());
        if (!pFile) {
            std::cerr << "[Bilingual] Failed to open voice map " << map_path << std::endl;
            return;
        }
        auto& file = *pFile;

        char header[4];
        file.read(header, 4);
        bool is_v2 = std::memcmp(header, "BLM2", 4) == 0;
        if (!is_v2 && std::memcmp(header, "BLMP", 4) != 0) {
            std::cerr << "[Bilingual] Invalid map header in " << map_path << std::endl;
            return;
        }

        uint32_t count;
        file.read(reinterpret_cast<char*>(&count), 4);
        std::cout << "[Bilingual] Loading " << count << " voice mappings from "
                  << map_path << " (v" << (is_v2 ? "2" : "1") << ")" << std::endl;

        out.reserve(count);
        for (uint32_t i = 0; i < count; i++) {
            VoiceMapping m;

            file.read(reinterpret_cast<char*>(&m.zh_func_id), 4);
            std::getline(file, m.zh_offset_key, '\0');

            uint16_t segment_raw;
            file.read(reinterpret_cast<char*>(&segment_raw), 2);
            m.zh_segment = segment_raw;

            file.read(reinterpret_cast<char*>(&m.en_func_id), 4);
            std::getline(file, m.en_offset_key, '\0');

            if (is_v2) {
                uint16_t en_segment_raw;
                file.read(reinterpret_cast<char*>(&en_segment_raw), 2);
                m.en_segment = en_segment_raw;
            } else {
                m.en_segment = segment_raw;
            }

            out.push_back(std::move(m));
        }

        std::cout << "[Bilingual] Successfully loaded " << out.size()
                  << " voice mappings from " << map_path << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "[Bilingual] Error loading voice map " << map_path << ": "
                  << e.what() << std::endl;
        out.clear();
    }
}

void BilingualManager::load_bilingual_map() {
    load_map_file("<PATCH>/voice_acting/bilingual_map.dat", bilingual_map);
    load_map_file("<PATCH>/voice_acting/dual_map.dat", dual_map);
}

void BilingualManager::set_text_language(TextLanguage lang) {
    if (lang == current_lang) return;

    Game_window* gwin = Game_window::get_instance();
    if (gwin) {
        gwin->set_usecode(get_usecode(lang));
        Game_singletons::init(gwin);
        current_lang = lang;
        gwin->set_all_dirty();
    }
}

Usecode_machine* BilingualManager::get_active_usecode() {
    return (current_lang == TextLanguage::DUAL) ? get_usecode(TextLanguage::DUAL)
           : (current_lang == TextLanguage::CHINESE && usecode_zh)
                   ? usecode_zh
                   : usecode_en;
}

Usecode_machine* BilingualManager::get_usecode(TextLanguage lang) {
    if (lang == TextLanguage::DUAL) {
        if (usecode_dual) {
            return usecode_dual;
        }
        if (usecode_zh) {    // File fallback: Chinese.
            return usecode_zh;
        }
        return usecode_en;
    }
    return (lang == TextLanguage::CHINESE) ? usecode_zh : usecode_en;
}

bool BilingualManager::map_offset(TextLanguage from_lang, int func_id,
                                   const std::string& offset_key,
                                   int segment,
                                   int& out_func_id, std::string& out_offset_key,
                                   int& out_segment) {
    if (from_lang == TextLanguage::CHINESE) {
        for (const auto& m : bilingual_map) {
            if (m.zh_func_id == func_id && m.zh_offset_key == offset_key
                    && m.zh_segment == segment) {
                out_func_id = m.en_func_id;
                out_offset_key = m.en_offset_key;
                out_segment = m.en_segment;
                return true;
            }
        }
    } else if (from_lang == TextLanguage::ENGLISH) {
        for (const auto& m : bilingual_map) {
            if (m.en_func_id == func_id && m.en_offset_key == offset_key
                    && m.en_segment == segment) {
                out_func_id = m.zh_func_id;
                out_offset_key = m.zh_offset_key;
                out_segment = m.zh_segment;
                return true;
            }
        }
    } else if (from_lang == TextLanguage::DUAL) {
        for (const auto& m : dual_map) {
            if (m.zh_func_id == func_id && m.zh_offset_key == offset_key
                    && m.zh_segment == segment) {
                out_func_id = m.en_func_id;
                out_offset_key = m.en_offset_key;
                out_segment = m.en_segment;
                return true;
            }
        }
    }
    return false;
}
