#include "databuf.h"
#include "audio/voice_composite.h"
#include "OggAudioSample.h"

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <memory>
#include <string>
#include <vector>

void assert_voice_pcm_chunks_keep_order_with_exact_gap() {
	const VoicePcmChunk first{1000, false, {11, 12}};
	const VoicePcmChunk second{1000, false, {21}};
	const VoicePcmResult result = compose_voice_pcm({first, second});
	assert(result.ok);
	assert(result.sample_rate == 1000);
	assert(!result.stereo);
	assert(result.pcm16.size() == 83);
	assert(result.pcm16[0] == 11);
	assert(result.pcm16[1] == 12);
	for (std::size_t i = 2; i < 82; ++i) {
		assert(result.pcm16[i] == 0);
	}
	assert(result.pcm16[82] == 21);
}

void assert_voice_pcm_rejects_empty_or_invalid_chunks() {
	assert(!compose_voice_pcm({}).ok);
	assert(!compose_voice_pcm({VoicePcmChunk{16000, false, {}}}).ok);
	assert(!compose_voice_pcm({VoicePcmChunk{0, false, {1}}}).ok);
	assert(!compose_voice_pcm({
			VoicePcmChunk{16000, false, {1}},
			VoicePcmChunk{22050, false, {2}}}).ok);
	assert(!compose_voice_pcm({
			VoicePcmChunk{16000, false, {1}},
			VoicePcmChunk{16000, true, {2, 3}}}).ok);
	assert(!compose_voice_pcm({
			VoicePcmChunk{16000, true, {1}},
			VoicePcmChunk{16000, true, {2, 3}}}).ok);
}

void assert_voice_pcm_rejects_output_size_overflow_without_partial_data() {
	const VoicePcmChunk first{
			std::numeric_limits<std::uint32_t>::max(), true, {1, 2}};
	const VoicePcmChunk second{
			std::numeric_limits<std::uint32_t>::max(), true, {3, 4}};
	const VoicePcmResult too_large = compose_voice_pcm(
			{first, second}, 3000);
	assert(!too_large.ok);
	assert(too_large.pcm16.empty());

	const VoicePcmResult arithmetic_overflow = compose_voice_pcm(
			{first, second},
			std::numeric_limits<std::uint64_t>::max());
	assert(!arithmetic_overflow.ok);
	assert(arithmetic_overflow.pcm16.empty());
}

std::vector<std::uint8_t> read_test_ogg() {
	std::ifstream file(VOICE_COMPOSITE_TEST_OGG, std::ios::binary | std::ios::ate);
	assert(file.is_open());
	const std::streamsize size = file.tellg();
	assert(size > 0);
	file.seekg(0, std::ios::beg);
	std::vector<std::uint8_t> data(static_cast<std::size_t>(size));
	assert(file.read(reinterpret_cast<char*>(data.data()), size));
	return data;
}

std::unique_ptr<std::uint8_t[]> copy_to_unique(const std::vector<std::uint8_t>& bytes) {
	auto buffer = std::make_unique<std::uint8_t[]>(bytes.size());
	std::copy(bytes.begin(), bytes.end(), buffer.get());
	return buffer;
}

std::vector<std::uint8_t> corrupt_last_ogg_page_payload(
		const std::vector<std::uint8_t>& encoded) {
	std::vector<std::pair<std::size_t, std::size_t>> pages;
	std::size_t position = 0;
	while (position + 27 <= encoded.size()) {
		while (position + 4 <= encoded.size()
				&& std::memcmp(encoded.data() + position, "OggS", 4) != 0) {
			++position;
		}
		if (position + 27 > encoded.size()) {
			break;
		}
		const std::size_t segment_count = encoded[position + 26];
		const std::size_t lacing_start = position + 27;
		if (segment_count > encoded.size() - lacing_start) {
			break;
		}
		std::size_t payload_size = 0;
		for (std::size_t index = 0; index < segment_count; ++index) {
			payload_size += encoded[lacing_start + index];
		}
		const std::size_t payload_start = lacing_start + segment_count;
		if (payload_size > encoded.size() - payload_start) {
			break;
		}
		const std::size_t page_end = payload_start + payload_size;
		pages.push_back({payload_start, page_end});
		position = page_end;
	}
	assert(pages.size() >= 3);
	const auto [payload_start, page_end] = pages.back();
	assert(page_end > payload_start);
	std::vector<std::uint8_t> corrupted = encoded;
	corrupted[payload_start + (page_end - payload_start) / 2] ^= 0x80;
	return corrupted;
}

void assert_ogg_decoder_returns_aligned_pcm_metadata() {
	const std::vector<std::uint8_t> encoded = read_test_ogg();
	Pentagram::OggAudioSample sample(
			copy_to_unique(encoded), static_cast<std::uint32_t>(encoded.size()));
	std::uint32_t rate = 0;
	bool stereo = true;
	std::vector<std::int16_t> pcm;
	std::string error;
	assert(sample.decode_pcm16(rate, stereo, pcm, error));
	assert(error.empty());
	assert(rate == 16000);
	assert(!stereo);
	assert(!pcm.empty());
	assert(pcm.size() % (stereo ? 2U : 1U) == 0);
}

void assert_ogg_decoder_rejects_corrupt_input_without_partial_pcm() {
	const std::vector<std::uint8_t> corrupt{'n', 'o', 't', ' ', 'o', 'g', 'g'};
	Pentagram::OggAudioSample sample(
			copy_to_unique(corrupt), static_cast<std::uint32_t>(corrupt.size()));
	std::uint32_t rate = 123;
	bool stereo = true;
	std::vector<std::int16_t> pcm{55, 56};
	std::string error;
	assert(!sample.decode_pcm16(rate, stereo, pcm, error));
	assert(!error.empty());
	assert(rate == 123);
	assert(stereo);
	assert((pcm == std::vector<std::int16_t>{55, 56}));
}

void assert_ogg_decoder_rejects_midstream_corruption_after_valid_headers() {
	const std::vector<std::uint8_t> damaged =
			corrupt_last_ogg_page_payload(read_test_ogg());
	IBufferDataView source(damaged.data(), damaged.size());
	assert(Pentagram::OggAudioSample::isThis(&source));
	Pentagram::OggAudioSample sample(
			copy_to_unique(damaged), static_cast<std::uint32_t>(damaged.size()));
	std::uint32_t rate = 123;
	bool stereo = true;
	std::vector<std::int16_t> pcm{55, 56};
	std::string error;
	assert(!sample.decode_pcm16(rate, stereo, pcm, error));
	assert(!error.empty());
	assert(error != "Could not open Ogg/Vorbis voice fragment.");
	assert(rate == 123);
	assert(stereo);
	assert((pcm == std::vector<std::int16_t>{55, 56}));
}

void assert_atomic_sequence_does_not_submit_after_later_decode_failure() {
	int decoded_count = 0;
	int submit_count = 0;
	const bool submitted = submit_voice_sequence_atomic(
			std::vector<std::string>{"first", "broken"}, 80,
			[&decoded_count](const std::string& path, VoicePcmChunk& chunk) {
				++decoded_count;
				if (path == "broken") {
					return false;
				}
				chunk = VoicePcmChunk{16000, false, {11}};
				return true;
			},
			[&submit_count](const VoicePcmResult&) {
				++submit_count;
				return true;
			});
	assert(!submitted);
	assert(decoded_count == 2);
	assert(submit_count == 0);
}

void assert_atomic_sequence_submits_one_composed_wav() {
	int submit_count = 0;
	std::vector<std::uint8_t> wav;
	const bool submitted = submit_voice_sequence_atomic(
			std::vector<std::string>{"first", "second"}, 80,
			[](const std::string& path, VoicePcmChunk& chunk) {
				chunk = VoicePcmChunk{16000, false, {static_cast<std::int16_t>(path == "first" ? 11 : 22)}};
				return true;
			},
			[&submit_count, &wav](const VoicePcmResult& pcm) {
				++submit_count;
				std::string error;
				return encode_voice_pcm_wav(pcm, wav, error) && error.empty();
			});
	assert(submitted);
	assert(submit_count == 1);
	assert(wav.size() == 44 + (2 + 1280) * sizeof(std::int16_t));
	assert(wav[0] == 'R' && wav[1] == 'I' && wav[2] == 'F' && wav[3] == 'F');
	assert(wav[44] == 11 && wav[45] == 0);
	assert(wav[44 + (1 + 1280) * sizeof(std::int16_t)] == 22);
}

void assert_atomic_sequence_does_not_submit_after_real_decode_failure() {
	const std::vector<std::uint8_t> valid = read_test_ogg();
	const std::vector<std::uint8_t> damaged = corrupt_last_ogg_page_payload(valid);
	int decoded_count = 0;
	int submit_count = 0;
	const bool submitted = submit_voice_sequence_atomic(
			std::vector<std::string>{"valid", "damaged"}, 80,
			[&](const std::string& path, VoicePcmChunk& chunk) {
				++decoded_count;
				const auto& bytes = path == "valid" ? valid : damaged;
				Pentagram::OggAudioSample sample(
						copy_to_unique(bytes), static_cast<std::uint32_t>(bytes.size()));
				std::string error;
				return sample.decode_pcm16(
						chunk.sample_rate, chunk.stereo, chunk.pcm16, error);
			},
			[&submit_count](const VoicePcmResult&) {
				++submit_count;
				return true;
			});
	assert(!submitted);
	assert(decoded_count == 2);
	assert(submit_count == 0);
}

int main() {
	assert_voice_pcm_chunks_keep_order_with_exact_gap();
	assert_voice_pcm_rejects_empty_or_invalid_chunks();
	assert_voice_pcm_rejects_output_size_overflow_without_partial_data();
	assert_ogg_decoder_returns_aligned_pcm_metadata();
	assert_ogg_decoder_rejects_corrupt_input_without_partial_pcm();
	assert_ogg_decoder_rejects_midstream_corruption_after_valid_headers();
	assert_atomic_sequence_does_not_submit_after_later_decode_failure();
	assert_atomic_sequence_submits_one_composed_wav();
	assert_atomic_sequence_does_not_submit_after_real_decode_failure();
	return EXIT_SUCCESS;
}
