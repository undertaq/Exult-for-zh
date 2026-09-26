#ifndef EXULT_VOICE_COMPOSITE_H
#define EXULT_VOICE_COMPOSITE_H

#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

struct VoicePcmChunk {
	std::uint32_t sample_rate = 0;
	bool stereo = false;
	std::vector<std::int16_t> pcm16;
};

struct VoicePcmResult {
	bool ok = false;
	std::uint32_t sample_rate = 0;
	bool stereo = false;
	std::vector<std::int16_t> pcm16;
	std::string error;
};

inline VoicePcmResult compose_voice_pcm(
		const std::vector<VoicePcmChunk>& chunks,
		std::uint64_t gap_ms = 80) {
	auto failure = [](const char* message) {
		VoicePcmResult result;
		result.error = message;
		return result;
	};
	if (chunks.empty()) {
		return failure("voice PCM sequence is empty");
	}
	const std::uint32_t sample_rate = chunks.front().sample_rate;
	const bool stereo = chunks.front().stereo;
	if (sample_rate == 0) {
		return failure("voice PCM sample rate is zero");
	}
	const std::size_t channels = stereo ? 2 : 1;
	for (const VoicePcmChunk& chunk : chunks) {
		if (chunk.pcm16.empty()) {
			return failure("voice PCM chunk is empty");
		}
		if (chunk.sample_rate == 0 || chunk.sample_rate != sample_rate) {
			return failure("voice PCM sample rates do not match");
		}
		if (chunk.stereo != stereo) {
			return failure("voice PCM channel counts do not match");
		}
		if (chunk.pcm16.size() % channels != 0) {
			return failure("voice PCM chunk is not frame-aligned");
		}
	}

	std::uint64_t gap_frames = 0;
	std::size_t gap_samples = 0;
	if (chunks.size() > 1 && gap_ms != 0) {
		const std::uint64_t rate = sample_rate;
		if (rate > std::numeric_limits<std::uint64_t>::max() / gap_ms) {
			return failure("voice PCM gap calculation overflow");
		}
		const std::uint64_t gap_units = rate * gap_ms;
		if (gap_units % 1000 != 0) {
			return failure("voice PCM gap is not an integral frame count");
		}
		gap_frames = gap_units / 1000;
		const std::size_t max_samples =
				(std::numeric_limits<std::uint32_t>::max() - 44U)
				/ sizeof(std::int16_t);
		if (gap_frames > max_samples / channels) {
			return failure("voice PCM gap exceeds sample size limit");
		}
		gap_samples = static_cast<std::size_t>(gap_frames) * channels;
	}

	const std::size_t max_samples =
			(std::numeric_limits<std::uint32_t>::max() - 44U)
			/ sizeof(std::int16_t);
	std::size_t output_samples = 0;
	for (std::size_t i = 0; i < chunks.size(); ++i) {
		if (chunks[i].pcm16.size() > max_samples - output_samples) {
			return failure("voice PCM output exceeds sample size limit");
		}
		output_samples += chunks[i].pcm16.size();
		if (i + 1 < chunks.size()) {
			if (gap_samples > max_samples - output_samples) {
				return failure("voice PCM output exceeds sample size limit");
			}
			output_samples += gap_samples;
		}
	}
	if (output_samples > std::vector<std::int16_t>().max_size()) {
		return failure("voice PCM output exceeds container size limit");
	}

	VoicePcmResult result;
	try {
		result.pcm16.reserve(output_samples);
		for (std::size_t i = 0; i < chunks.size(); ++i) {
			result.pcm16.insert(
					result.pcm16.end(), chunks[i].pcm16.begin(), chunks[i].pcm16.end());
			if (i + 1 < chunks.size()) {
				result.pcm16.insert(result.pcm16.end(), gap_samples, 0);
			}
		}
	} catch (const std::bad_alloc&) {
		return failure("voice PCM allocation failed");
	} catch (const std::length_error&) {
		return failure("voice PCM output exceeds container size limit");
	}
	result.ok = true;
	result.sample_rate = sample_rate;
	result.stereo = stereo;
	return result;
}

inline bool encode_voice_pcm_wav(
		const VoicePcmResult& pcm, std::vector<std::uint8_t>& wav,
		std::string& error) {
	if (!pcm.ok || pcm.sample_rate == 0 || pcm.pcm16.empty()) {
		error = "voice PCM result is incomplete";
		return false;
	}
	const std::uint32_t channels = pcm.stereo ? 2 : 1;
	const std::uint64_t byte_rate = static_cast<std::uint64_t>(pcm.sample_rate) * channels * 2;
	const std::size_t max_samples =
			(std::numeric_limits<std::uint32_t>::max() - 44U) / sizeof(std::int16_t);
	if (pcm.pcm16.size() % channels != 0 || pcm.pcm16.size() > max_samples
			|| byte_rate > std::numeric_limits<std::uint32_t>::max()) {
		error = "voice PCM cannot be represented as a WAV sample";
		return false;
	}
	const std::uint32_t data_size = static_cast<std::uint32_t>(pcm.pcm16.size() * sizeof(std::int16_t));
	auto write_u16 = [](std::vector<std::uint8_t>& target, std::uint16_t value) {
		target.push_back(static_cast<std::uint8_t>(value & 0xffU));
		target.push_back(static_cast<std::uint8_t>(value >> 8));
	};
	auto write_u32 = [](std::vector<std::uint8_t>& target, std::uint32_t value) {
		target.push_back(static_cast<std::uint8_t>(value & 0xffU));
		target.push_back(static_cast<std::uint8_t>((value >> 8) & 0xffU));
		target.push_back(static_cast<std::uint8_t>((value >> 16) & 0xffU));
		target.push_back(static_cast<std::uint8_t>(value >> 24));
	};
	std::vector<std::uint8_t> encoded;
	try {
		encoded.reserve(static_cast<std::size_t>(data_size) + 44);
		const auto write_tag = [&encoded](const char* tag) {
			encoded.insert(encoded.end(), tag, tag + 4);
		};
		write_tag("RIFF");
		write_u32(encoded, data_size + 36U);
		write_tag("WAVE");
		write_tag("fmt ");
		write_u32(encoded, 16);
		write_u16(encoded, 1);
		write_u16(encoded, static_cast<std::uint16_t>(channels));
		write_u32(encoded, pcm.sample_rate);
		write_u32(encoded, static_cast<std::uint32_t>(byte_rate));
		write_u16(encoded, static_cast<std::uint16_t>(channels * 2));
		write_u16(encoded, 16);
		write_tag("data");
		write_u32(encoded, data_size);
		for (const std::int16_t sample : pcm.pcm16) {
			write_u16(encoded, static_cast<std::uint16_t>(sample));
		}
	} catch (const std::bad_alloc&) {
		error = "voice WAV allocation failed";
		return false;
	} catch (const std::length_error&) {
		error = "voice WAV exceeds container size limit";
		return false;
	}
	wav.swap(encoded);
	error.clear();
	return true;
}

template <typename DecodeFragment, typename SubmitSample>
inline bool submit_voice_sequence_atomic(
		const std::vector<std::string>& paths, std::uint64_t gap_ms,
		DecodeFragment&& decode_fragment, SubmitSample&& submit_sample) {
	if (paths.empty()) {
		return false;
	}
	std::vector<VoicePcmChunk> chunks;
	try {
		chunks.reserve(paths.size());
		for (const std::string& path : paths) {
			VoicePcmChunk chunk;
			if (!decode_fragment(path, chunk)) {
				return false;
			}
			chunks.push_back(std::move(chunk));
		}
	} catch (const std::bad_alloc&) {
		return false;
	} catch (const std::length_error&) {
		return false;
	}
	try {
		VoicePcmResult composed = compose_voice_pcm(chunks, gap_ms);
		return composed.ok && submit_sample(composed);
	} catch (const std::bad_alloc&) {
		return false;
	} catch (const std::length_error&) {
		return false;
	}
}

#endif
