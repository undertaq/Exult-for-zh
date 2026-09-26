/*
Copyright (C) 2010-2022 The Exult Team

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
*/

#include "pent_include.h"

#include "OggAudioSample.h"

#include "databuf.h"
#include "headers/exceptions.h"

#include <new>
#include <array>
#include <limits>
#include <exception>

#ifdef __GNUC__
#	pragma GCC diagnostic push
#	pragma GCC diagnostic ignored "-Wold-style-cast"
#	pragma GCC diagnostic ignored "-Wzero-as-null-pointer-constant"
#	if !defined(__llvm__) && !defined(__clang__)
#		pragma GCC diagnostic ignored "-Wuseless-cast"
#	endif
#endif    // __GNUC__
#include <SDL3/SDL.h>
#ifdef __GNUC__
#	pragma GCC diagnostic pop
#endif    // __GNUC__

namespace Pentagram {

	ov_callbacks OggAudioSample::callbacks = {&read_func, &seek_func, nullptr, &tell_func};

	OggAudioSample::OggAudioSample(std::unique_ptr<IDataSource> oggdata_) : AudioSample(nullptr, 0), oggdata(std::move(oggdata_)) {
		frame_size         = 4096;
		decompressor_size  = sizeof(OggDecompData);
		decompressor_align = alignof(OggDecompData);
		bits               = 16;
		locked             = false;
		// we set this in initDecompressor
		length = 0;
	}

	OggAudioSample::OggAudioSample(std::unique_ptr<uint8[]> buffer, uint32 size)
			: AudioSample(std::move(buffer), size), oggdata(nullptr) {
		frame_size         = 4096;
		decompressor_size  = sizeof(OggDecompData);
		decompressor_align = alignof(OggDecompData);
		bits               = 16;
		locked             = false;
		// we set this in initDecompressor
		length = 0;
	}

	size_t OggAudioSample::read_func(void* ptr, size_t size, size_t nmemb, void* datasource) {
		auto* ids = static_cast<IDataSource*>(datasource);
		if (size == 0 || nmemb == 0 || nmemb > std::numeric_limits<size_t>::max() / size) {
			return 0;
		}
		const size_t limit = ids->getAvail();
		if (limit < size * nmemb) {
			nmemb = limit / size;
		}
		if (nmemb == 0) {
			return 0;
		}
		ids->read(ptr, size * nmemb);
		return nmemb;
	}

	int OggAudioSample::seek_func(void* datasource, ogg_int64_t offset, int whence) {
		auto* ids = static_cast<IDataSource*>(datasource);
		size_t base = 0;
		switch (whence) {
		case SEEK_SET:
			base = 0;
			break;
		case SEEK_END:
			base = ids->getSize();
			break;
		case SEEK_CUR:
			base = ids->getPos();
			break;
		default:
			return -1;
		}

		size_t target = 0;
		if (base > ids->getSize()) {
			return -1;
		}
		if (offset < 0) {
			const auto distance = static_cast<uint64>(-(offset + 1)) + 1;
			if (distance > base) {
				return -1;
			}
			target = base - static_cast<size_t>(distance);
		} else {
			const auto distance = static_cast<uint64>(offset);
			if (distance > ids->getSize() - base) {
				return -1;
			}
			target = base + static_cast<size_t>(distance);
		}
		ids->seek(target);
		return ids->fail() ? -1 : 0;
	}

	long OggAudioSample::tell_func(void* datasource) {
		auto* ids = static_cast<IDataSource*>(datasource);
		const size_t position = ids->getPos();
		if (static_cast<uint64>(position) > static_cast<uint64>(std::numeric_limits<long>::max())) {
			return -1;
		}
		return static_cast<long>(position);
	}

	bool OggAudioSample::isThis(IDataSource* oggdata) {
		OggVorbis_File vf;
		oggdata->seek(0);
		const int res = ov_test_callbacks(oggdata, &vf, nullptr, 0, callbacks);
		if (res == 0) {
			ov_clear(&vf);
		}

		return res == 0;
	}

	void OggAudioSample::initDecompressor(void* DecompData) const {
		if (oggdata && locked) {
			throw exult_exception("Attempted to play OggAudioSample on more "
							  "than one channel at the same time.");
		}
		auto* decomp = new (DecompData) OggDecompData{};

		try {
			if (oggdata) {
				locked = true;
				decomp->datasource = oggdata.get();
			} else {
				decomp->datasource = new IBufferDataView(buffer, buffer_limit);
			}

			decomp->datasource->seek(0);
			const int open_result = ov_open_callbacks(decomp->datasource, &decomp->ov, nullptr, 0, callbacks);
			if (open_result != 0) {
				throw exult_exception("Could not open Ogg/Vorbis voice fragment.");
			}
			decomp->opened = true;

			vorbis_info* info = ov_info(&decomp->ov, -1);
			if (!info || info->rate <= 0
					|| static_cast<uint64>(info->rate) > std::numeric_limits<uint32>::max()
					|| (info->channels != 1 && info->channels != 2)) {
				throw exult_exception("Ogg/Vorbis voice fragment has unsupported audio metadata.");
			}
			sample_rate = decomp->last_rate = static_cast<uint32>(info->rate);
			stereo = decomp->last_stereo = info->channels == 2;

			// Keep the mixer length bounded to the public sample-length type.
			const ogg_int64_t frames = ov_pcm_total(&decomp->ov, -1);
			if (frames >= 0 && static_cast<uint64>(frames) <= std::numeric_limits<uint32>::max()) {
				length = static_cast<uint32>(frames);
			}
			if (ov_raw_seek(&decomp->ov, 0) != 0) {
				throw exult_exception("Could not rewind Ogg/Vorbis voice fragment.");
			}
			decomp->freed = false;
		} catch (...) {
			if (decomp->opened) {
				ov_clear(&decomp->ov);
				decomp->opened = false;
			}
			if (oggdata) {
				locked = false;
			} else {
				delete decomp->datasource;
			}
			decomp->datasource = nullptr;
			decomp->~OggDecompData();
			throw;
		}
	}

	void OggAudioSample::freeDecompressor(void* DecompData) const {
		auto* decomp = static_cast<OggDecompData*>(DecompData);
		if (decomp->freed) {
			return;
		}
		decomp->freed = true;
		if (decomp->opened) {
			ov_clear(&decomp->ov);
			decomp->opened = false;
		}

		if (this->oggdata) {
			locked = false;
		} else {
			delete decomp->datasource;
		}

		decomp->datasource = nullptr;
		decomp->~OggDecompData();
	}

	void OggAudioSample::rewind(void* DecompData) const {
		auto* decomp = static_cast<OggDecompData*>(DecompData);
		if (ov_raw_seek(&decomp->ov, 0) != 0) {
			// If raw seek fails just call themuch more expensive method in the
			// base class
			AudioSample::rewind(DecompData);
		}
	}

	uint32 OggAudioSample::decompressFrame(void* DecompData, void* samples) const {
		auto* decomp = static_cast<OggDecompData*>(DecompData);

		vorbis_info* info = ov_info(&decomp->ov, -1);

		if (info == nullptr) {
			return 0;
		}

		sample_rate         = decomp->last_rate;
		stereo              = decomp->last_stereo;
		decomp->last_rate   = info->rate > 0 ? static_cast<uint32>(info->rate) : 0;
		decomp->last_stereo = info->channels == 2;

#if SDL_BYTEORDER == SDL_LIL_ENDIAN
		const int bigendianp = 0;
#else
		const int bigendianp = 1;
#endif

		const long count = ov_read(&decomp->ov, static_cast<char*>(samples), frame_size, bigendianp, 2, 1, &decomp->bitstream);

		if (count < 0) {
			decomp->last_error = static_cast<int>(count);
			return 0;
		}
		if (count == 0) {
			return 0;
		}
		return count;
	}

	bool OggAudioSample::decode_pcm16(
			uint32& rate, bool& is_stereo, std::vector<std::int16_t>& pcm,
			std::string& error) const {
		alignas(OggDecompData) unsigned char storage[sizeof(OggDecompData)]{};
		void* const state = storage;
		bool initialized = false;
		std::vector<std::int16_t> decoded;
		try {
			initDecompressor(state);
			initialized = true;
			const uint32 decoded_rate = sample_rate;
			const bool decoded_stereo = stereo;
			const uint32 channels = decoded_stereo ? 2 : 1;
			std::array<std::int16_t, 2048> frame{};
			while (true) {
				const uint32 byte_count = decompressFrame(state, frame.data());
				auto* decomp = static_cast<OggDecompData*>(state);
				if (byte_count == 0) {
					if (decomp->last_error != 0) {
						throw exult_exception("Error while decoding Ogg/Vorbis voice fragment.");
					}
					break;
				}
				if (byte_count % (channels * sizeof(std::int16_t)) != 0) {
					throw exult_exception("Decoded Ogg/Vorbis voice fragment is not frame-aligned.");
				}
				vorbis_info* info = ov_info(&decomp->ov, decomp->bitstream);
				if (!info || info->rate != static_cast<long>(decoded_rate)
						|| info->channels != static_cast<int>(channels)) {
					throw exult_exception("Ogg/Vorbis voice fragment changes format mid-stream.");
				}
				const std::size_t sample_count = byte_count / sizeof(std::int16_t);
				decoded.insert(decoded.end(), frame.begin(), frame.begin() + sample_count);
			}
			freeDecompressor(state);
			initialized = false;
		} catch (const std::exception& exception) {
			if (initialized) {
				freeDecompressor(state);
			}
			error = exception.what();
			return false;
		} catch (...) {
			if (initialized) {
				freeDecompressor(state);
			}
			error = "Unknown Ogg/Vorbis decode error.";
			return false;
		}
		if (decoded.empty()) {
			error = "Ogg/Vorbis voice fragment decoded to no PCM samples.";
			return false;
		}
		error.clear();
		rate = sample_rate;
		is_stereo = stereo;
		pcm.swap(decoded);
		return true;
	}

}    // namespace Pentagram
