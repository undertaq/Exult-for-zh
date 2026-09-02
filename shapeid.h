/*
 *  Copyright (C) 2000-2022  The Exult Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 */

#ifndef SHAPEID_H
#define SHAPEID_H 1

#include "endianio.h"
#include "exult_constants.h"
#include "fontvga.h"
#include "gamerend/iso_raster.h"
#include "gamerend/iso_projection.h"
#include "shapevga.h"
#include "singles.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <vector>

class Shape_frame;
class Shape_info;
class Font;
class Image_buffer;
class Image_buffer8;
struct Cursor_info;

enum ShapeFile {
	SF_SHAPES_VGA = 0,     // <STATIC>/shapes.vga.  MUST be first.
	SF_GUMPS_VGA,          // <STATIC>/gumps.vga
	SF_PAPERDOL_VGA,       // <STATIC>/paperdol.vga
	SF_SPRITES_VGA,        // <STATIC>/sprites.vga
	SF_FACES_VGA,          // <STATIC>/faces.vga
	SF_EXULT_FLX,          // <DATA>/exult.flx
	SF_GAME_FLX,           // <DATA>/bg_data.flx or <DATA>/si_data.flx
	SF_SHORTCUTBAR_VGA,    // EXULT_FLX_SHORTCUTBAR_VGA in <DATA>/exult.flx
	// Not yet
	// SF_FONTS_VGA,     // <STATIC>/fonts.vga
	SF_OTHER,    // Other unknown FLX
	SF_COUNT     // # of preceding entries.
};

// The original VGA data does not carry a general-purpose draw-type field.
// Keep this table deliberately conservative: only shape families explicitly
// identified as walls opt into the vertical-face rasterizer. All other terrain
// remains on the existing projected terrain path.
inline std::optional<IsoWallOrientation> iso_wall_orientation_for_shape(
		int shapenum, int framenum = 0) {
	std::optional<IsoWallOrientation> orientation;
	const int base_frame = framenum & 31;
	switch (shapenum) {
	case 151:    // 8x32 wall family: runs along the world-Y axis.
		if (base_frame >= 12) {
			return std::nullopt;
		}
		orientation = IsoWallOrientation::WorldY;
		break;
	case 152:    // 32x8 wall family: runs along the world-X axis.
		if (base_frame >= 14) {
			return std::nullopt;
		}
		orientation = IsoWallOrientation::WorldX;
		break;
	case 869:    // Additional 32x8 wall family.
		if (base_frame != 8 && base_frame != 9 && base_frame != 13) {
			return std::nullopt;
		}
		orientation = IsoWallOrientation::WorldX;
		break;
	default:
		return std::nullopt;
	}
	// Bit 5 denotes the reflected frame in Exult's shape encoding. Reflection
	// swaps the two world-facing wall axes, so it must also select the opposite
	// projected plane.
	if ((framenum & (1 << 5)) != 0) {
		*orientation = *orientation == IsoWallOrientation::WorldX
				? IsoWallOrientation::WorldY
				: IsoWallOrientation::WorldX;
	}
	return orientation;
}

// Build the cuboid atlas profile used by the explicitly identified wall
// frames. The source rectangles follow the compact VGA layout used by U7:
// the top face is at the upper-left, the long vertical face is below it, and
// the short vertical face is to its right. Reflected frames exchange the
// long world axis and therefore use the transposed layout.
inline std::optional<IsoWallProfile> iso_wall_profile_for_shape(
		int shapenum, int framenum, int source_width, int source_height,
		int wall_height_lifts) {
	const auto orientation = iso_wall_orientation_for_shape(shapenum, framenum);
	if (!orientation || source_width <= 0 || source_height <= 0) {
		return std::nullopt;
	}

	const int base_frame = framenum & 31;
	const bool reflected = (framenum & (1 << 5)) != 0;
	const auto clamp_face = [source_width, source_height](
			int x, int y, int width, int height) {
		IsoWallFace face;
		face.x = std::max(0, std::min(x, source_width));
		face.y = std::max(0, std::min(y, source_height));
		face.width = std::max(0, std::min(width, source_width - face.x));
		face.height = std::max(0, std::min(height, source_height - face.y));
		return face;
	};

	IsoWallProfile profile;
	profile.orientation = *orientation;
	profile.wall_height_lifts = std::max(1, wall_height_lifts);
	IsoWallFace canonical_top;
	IsoWallFace canonical_front;
	IsoWallFace canonical_right;
	if (shapenum == 151) {
		// The reference layout has a narrow-X/long-Y footprint. The face
		// rectangles vary slightly with the frame's artwork, so retain the
		// explicit atlas measurements rather than deriving them from the
		// bounding box.
		static constexpr int narrow_layouts[12][4] = {
				{32, 22, 8, 25}, {31, 22, 3, 25}, {31, 22, 3, 25},
				{32, 21, 8, 20}, {32, 20, 8, 20}, {32, 19, 8, 20},
				{32, 24, 8, 28}, {32, 24, 8, 25}, {32, 22, 8, 21},
				{32, 23, 8, 59}, {32, 20, 8, 20}, {32, 21, 8, 18}};
		const auto& layout = narrow_layouts[base_frame];
		profile.footprint_width_tiles = 1;
		profile.footprint_height_tiles = 4;
		canonical_top = clamp_face(0, 0, 8, 32);
		canonical_front = clamp_face(0, layout[0], 8, layout[1]);
		canonical_right = clamp_face(layout[2], 0, layout[3], 32);
	} else {
		// Shapes 152 and the confirmed wall frames of 869 use the
		// long-X/narrow-Y atlas layout.
		static constexpr int long_layouts[14][4] = {
				{8, 27, 32, 20}, {8, 20, 32, 21}, {1, 27, 32, 20},
				{8, 20, 32, 21}, {8, 20, 32, 19}, {8, 20, 32, 19},
				{8, 25, 32, 27}, {8, 26, 32, 30}, {8, 24, 32, 22},
				{8, 20, 32, 21}, {8, 20, 32, 23}, {8, 20, 32, 21},
				{8, 20, 32, 21}, {8, 6, 32, 19}};
		int front_y = 8;
		int front_height = source_height - front_y;
		int right_width = source_width - 32;
		if (shapenum == 152) {
			const auto& layout = long_layouts[base_frame];
			front_y = layout[0];
			front_height = layout[1];
			right_width = layout[3];
		} else {
			// Only frames 8, 9 and 13 reach this branch. Their layouts are
			// the wall_*.gltf variants in U7Revisited's shape table.
			front_height = 17;
			right_width = base_frame == 9 ? 19 : 20;
		}
		profile.footprint_width_tiles = 4;
		profile.footprint_height_tiles = 1;
		canonical_top = clamp_face(0, 0, 32, 8);
		canonical_front = clamp_face(0, front_y, 32, front_height);
		canonical_right = clamp_face(32, 0, right_width, 8);
	}
	if (!reflected) {
		profile.top = canonical_top;
		profile.front = canonical_front;
		profile.right = canonical_right;
	} else {
		// Shape_frame::reflect transposes the square source canvas. The
		// original right face becomes the reflected front face and vice
		// versa, while the footprint axes exchange their lengths.
		const auto transpose = [&clamp_face](const IsoWallFace& face) {
			return clamp_face(face.y, face.x, face.height, face.width);
		};
		profile.top = transpose(canonical_top);
		profile.front = transpose(canonical_right);
		profile.right = transpose(canonical_front);
		std::swap(
				profile.footprint_width_tiles,
				profile.footprint_height_tiles);
	}
	return profile;
}

// Special pixels.
enum Pixel_colors {
	BLACK_PIXEL = 0,
	POISON_PIXEL,
	PROTECT_PIXEL,
	CURSED_PIXEL,
	CHARMED_PIXEL,
	HIT_PIXEL,
	PARALYZE_PIXEL,
	NPIXCOLORS,
	MAGICCYCLE_PIXEL   = -226,    // Cyan-white palette cycle
	FIRECYCLE_PIXEL    = -236,    // Yellow-Red palete Cycle
	GREENCYCLE_PIXEL   = -242,    // Green palette cycle
	MAGENTACYCLE_PIXEL = -246,    // Magenta Palette cycle
	YELLOWCYCLE_PIXEL  = -249,    // White Yellow Palette cycle
	RYBCYCLE_PIXEL     = -252,    // Red Yellow Black Palette Cycle
};

/*
 *  Manage the set of shape files.
 */
class Shape_manager : public Game_singletons {
public:
	struct Cached_shape {
		Shape_frame* shape;
		bool         has_trans;
	};

private:
	static Shape_manager*           instance;                             // There shall be only one.
	Shapes_vga_file                 shapes;                               // Main 'shapes.vga' file.
	Vga_file                        files[static_cast<int>(SF_COUNT)];    // The files we manage.
	std::unique_ptr<Fonts_vga_file> fonts = nullptr;                      // "fonts.vga" file.
	std::vector<Xform_palette>      xforms;                               // Transforms translucent colors
	//   0xf4 through 0xfe.
	Xform_palette* invis_xform;                    // For showing invisible NPC's.
	unsigned char  special_pixels[NPIXCOLORS];     // Special colors.
	bool           can_have_paperdolls = false;    // Set true if the SI paperdoll file
	//   is found when playing BG
	bool paperdolls_enabled = false;    // True if paperdolls are on.
	bool got_si_shapes      = false;    // Set true if the SI shapes file
	//   is found when playing BG
	using Shape_cache = std::map<std::pair<int, int>, Cached_shape>;
	Shape_cache shape_cache[static_cast<int>(SF_COUNT)];
	void        read_shape_info();

public:
	friend class ShapeID;
	Shape_manager();
	~Shape_manager();

	static Shape_manager* get_instance() {
		return instance;
	}

	void load();                           // Read in files.
	bool load_gumps_minimal();             // Read in files needed to display gumps.
	void reload_shapes(int shape_kind);    // Reload a shape file.
	void reload_fonts(
			const File_spec& font_source,
			const File_spec& font_patch = PATCH_FONTS);    // Reload fonts from a different source.
	void reload_shape_info();

	static unsigned char get_special_pixel(int pixel) {
		if (pixel > -256 && pixel < 0) {
			return -pixel;
		} else if (pixel >= 0 && pixel < NPIXCOLORS) {
			return get_instance()->special_pixels[pixel];
		}
		return 255;
	}

	bool are_gumps_loaded() {
		return !shape_cache[SF_GUMPS_VGA].empty();
	}

	Vga_file& get_file(ShapeFile f) {
		return files[static_cast<int>(f)];
	}

	Shapes_vga_file& get_shapes() {
		return shapes;
	}

	inline Xform_palette& get_xform(int i) {
		return xforms[i];
	}

	// BG Only
	inline bool can_use_paperdolls() const {
		return can_have_paperdolls;
	}

	inline bool are_paperdolls_enabled() const {
		return paperdolls_enabled;
	}

	inline void set_paperdoll_status(bool p) {
		paperdolls_enabled = p;
	}

	inline bool have_si_shapes() const {
		return got_si_shapes;
	}

	// Paint shape in window.
	void paint_shape(int xoff, int yoff, Shape_frame* shape, bool translucent = false, unsigned char* trans = nullptr) {
		if (!shape || !shape->get_data()) {
			CERR("nullptr SHAPE!!!");
		} else if (!shape->is_rle()) {
			shape->paint(xoff, yoff);
		} else if (trans) {
			shape->paint_rle_remapped(xoff, yoff, trans);
		} else if (!translucent) {
			shape->paint_rle(xoff, yoff);
		} else {
			shape->paint_rle_translucent(xoff, yoff, xforms.data(), xforms.size());
		}
	}

	void paint_world_tile(
			int xoff, int yoff, Shape_frame* shape, bool translucent = false,
			unsigned char* trans = nullptr, int footprint_width = c_tilesize,
			int footprint_height = c_tilesize, int elevation_height = c_tilesize) {
		if (!shape || !shape->get_data()) {
			CERR("nullptr SHAPE!!!");
			return;
		}
		// RLE entries in terrain chunks are placed world art (walls, roofs,
		// and similar overlays). Only raw 8x8 frames are ground-plane tiles.
		if (shape->is_rle()) {
			paint_world_shape(
					xoff, yoff, shape, translucent, trans, footprint_width,
					footprint_height, elevation_height);
			return;
		}
		const IsoKind kind = IsoProjection::current().kind;
		if (kind == IsoKind::Legacy) {
			paint_shape(xoff, yoff, shape, translucent, trans);
		} else if (trans) {
			shape->paint_projected(xoff, yoff, kind, nullptr, 0, trans);
		} else if (!translucent) {
			shape->paint_projected(xoff, yoff, kind, nullptr, 0, nullptr);
		} else {
			shape->paint_projected(xoff, yoff, kind, xforms.data(), xforms.size(), nullptr);
		}
	}

	void paint_world_shape(
			int xoff, int yoff, Shape_frame* shape, bool translucent = false,
			unsigned char* trans = nullptr, int footprint_width = c_tilesize,
			int footprint_height = c_tilesize, int elevation_height = c_tilesize) {
		if (!shape || !shape->get_data()) {
			CERR("nullptr SHAPE!!!");
			return;
		}
		const IsoKind kind = IsoProjection::current().kind;
		if (kind == IsoKind::Legacy) {
			paint_shape(xoff, yoff, shape, translucent, trans);
		} else if (trans) {
			shape->paint_projected_world(
					xoff, yoff, kind, nullptr, 0, trans, footprint_width,
					footprint_height, elevation_height);
		} else if (!translucent) {
			shape->paint_projected_world(
					xoff, yoff, kind, nullptr, 0, nullptr, footprint_width,
					footprint_height, elevation_height);
		} else {
			shape->paint_projected_world(
					xoff, yoff, kind, xforms.data(), xforms.size(), nullptr,
					footprint_width, footprint_height, elevation_height);
		}
	}

	// Paint terrain wall/overlay art with the dedicated vertical-plane
	// transform. This is intentionally separate from paint_world_shape so
	// ordinary projected sprites keep their existing rasterization.
	void paint_world_wall(
			int xoff, int yoff, Shape_frame* shape, bool translucent,
			unsigned char* trans, const IsoWallProfile& profile) {
		if (!shape || !shape->get_data()) {
			CERR("nullptr SHAPE!!!");
			return;
		}
		const IsoKind kind = IsoProjection::current().kind;
		if (kind == IsoKind::Legacy) {
			paint_shape(xoff, yoff, shape, translucent, trans);
		} else if (trans) {
			shape->paint_projected_world_wall(
					xoff, yoff, kind, nullptr, 0, trans, profile);
		} else if (!translucent) {
			shape->paint_projected_world_wall(
					xoff, yoff, kind, nullptr, 0, nullptr, profile);
		} else {
			shape->paint_projected_world_wall(
					xoff, yoff, kind, xforms.data(), xforms.size(), nullptr,
					profile);
		}
	}

	// Paint scaled shape in window.
	void paint_shape_scaled(int xoff, int yoff, int scale, Shape_frame* shape, bool translucent = false, unsigned char* trans = nullptr) {
		if (!shape || !shape->get_data()) {
			CERR("nullptr SHAPE!!!");
		} else if (!shape->is_rle()) {
			shape->paint(xoff, yoff);
		} else if (trans) {
			shape->paint_rle_remapped_scaled(xoff, yoff, scale, trans);
		} else if (!translucent) {
			shape->paint_rle_scaled(xoff, yoff, scale);
		} else {
			shape->paint_rle_translucent_scaled(xoff, yoff, scale, xforms.data(), xforms.size());
		}
	}

	inline void paint_invisible(int xoff, int yoff, Shape_frame* shape) {
		if (shape) {
			shape->paint_rle_transformed(xoff, yoff, *invis_xform);
		}
	}

	// Paint outline around a shape.
	inline void paint_outline(int xoff, int yoff, Shape_frame* shape, int special_pixel) {
		if (shape) {
			shape->paint_rle_outline(xoff, yoff, get_special_pixel(special_pixel));
		}
	}

	// Paint text using "fonts.vga".
	int paint_text_box(
			int fontnum, const char* text, int x, int y, int w, int h, int vert_lead = 0, bool pbreak = false, bool center = false,
			int shading = -1, Cursor_info* cursor = nullptr, bool force_cjk = false);
	int paint_text(int fontnum, const char* text, int xoff, int yoff, bool force_cjk = false);
	int paint_text(int fontnum, const char* text, int textlen, int xoff, int yoff, bool force_cjk = false);
	int paint_text(std::shared_ptr<Font> font, const char* text, int xoff, int yoff, bool force_cjk = false);
	int paint_text(std::shared_ptr<Font> font, const char* text, int textlen, int xoff, int yoff, bool force_cjk = false);
	// Get text width.
	int get_text_width(int fontnum, const char* text, bool force_cjk = false);
	int get_text_width(int fontnum, const char* text, int textlen, bool force_cjk = false);
	// Get text height, baseline.
	int get_text_height(int fontnum);
	// Get text height including vertical leading (for line spacing).
	int                   get_text_line_height(int fontnum);
	int                   get_text_baseline(int fontnum);
	int                   find_cursor(int fontnum, const char* text, int x, int y, int w, int h, int cx, int cy, int vert_lead);
	std::shared_ptr<Font> get_font(int fontnum);

	size_t get_xforms_cnt() const {
		return xforms.size();
	}

	Cached_shape cache_shape(int shape_kind, int shapenum, int framenum);
};

/*
 *  A shape ID contains a shape # and a frame # within the shape encoded
 *  as a 2-byte quantity.
 */
class ShapeID : public Game_singletons {
	short       shapenum          = -1;    // Shape #.
	signed char framenum          = -1;    // Frame # within shape.
	uint16      palette_transform = 0;

	ShapeFile shapefile = SF_SHAPES_VGA;

	Shape_manager::Cached_shape cache_shape() const;

public:
	// Read from buffer & incr. ptr.
	ShapeID(unsigned char*& data) {
		const unsigned char l = Read1(data);
		const unsigned char h = Read1(data);
		shapenum              = l + 256 * (h & 0x3);
		framenum              = h >> 2;
		// this is not saved
		palette_transform = 0;
	}

	// Create "end-of-list"/invalid entry.
	ShapeID() = default;

	ShapeID(const ShapeID&)                = default;
	ShapeID& operator=(const ShapeID&)     = default;
	ShapeID(ShapeID&&) noexcept            = default;
	ShapeID& operator=(ShapeID&&) noexcept = default;
	virtual ~ShapeID()                     = default;

	// End-of-list or invalid?
	bool is_invalid() const {
		return shapenum == -1;
	}

	bool is_eol() const {
		return is_invalid();
	}

	inline int get_shapenum() const {
		return shapenum;
	}

	inline int get_framenum() const {
		return framenum;
	}

	inline ShapeFile get_shapefile() const {
		return shapefile;
	}

	inline Shape_frame* get_shape() const {
		return cache_shape().shape;
	}

	inline bool is_translucent() const {
		return cache_shape().has_trans;
	}

	// Set to given shape.
	void set_shape(int shnum, int frnum) {
		shapenum = shnum;
		framenum = frnum;
	}

	ShapeID(int shnum, int frnum, ShapeFile shfile = SF_SHAPES_VGA)
			: shapenum(shnum), framenum(frnum), palette_transform(0), shapefile(shfile) {}

	void set_shape(int shnum) {    // Set shape, but keep old frame #.
		shapenum = shnum;
	}

	void set_frame(int frnum) {    // Set to new frame.
		framenum = frnum;
	}

	//
	// Palette transformations
	//
	// see comment on set_palette_transform for what this is all about
	//

public:
	//! Palette tranformation types to use with #set_palette_transform
	enum PaletteTransformType {
		//! Basic palette index shift
		//! Use PT_Shift|(offset mod 256)
		PT_Shift = 0,

		//!  transform using an xform table as if there was a transparent
		//!  overlay drawn over the
		//! shape  Use (PT_xForm|xform number)
		PT_xForm = 1 << 8,

		//! Ramp remapping to remaap a single ramp
		//! Use (PT_RampRemap|rampfrom<<5|rampto&31)
		PT_RampRemap = 1 << 15,

		//! Ramp remapping to remap all ramps.
		//! Use (PT_RampRemapAllFrom|rampto&31)
		PT_RampRemapAllFrom = PT_RampRemap | 255 << 5
	};

	//! Palette transformation to use when painting shape if not transparent.
	//! \param pt New Palette transform to use. See ShapeId::PaletteTransformType
	//! \remark Note Behaviour on palette cycling, a shift can shift a colour into
	//! the palette cycling range for interesting effects, or shift cycling
	//! colours out of the range Xform will get rid of all palette cycling
	//! effects.
	void set_palette_transform(int pt) {
		palette_transform = pt;
	}

	int get_palette_transform() const {
		return palette_transform;
	}

	void set_file(ShapeFile shfile) {    // Set to new flex
		shapefile = shfile;
	}

	void paint_shape(int xoff, int yoff, std::optional<bool> force_trans = std::nullopt) const {
		auto           cache      = cache_shape();
		unsigned char* transtable = nullptr;
		unsigned char  table[256];
		if (palette_transform != 0) {
			transtable = Get_palette_transform_table(table);
		}
		sman->paint_shape(xoff, yoff, cache.shape, force_trans ? *force_trans : cache.has_trans, transtable);
	}

	void paint_world_shape(int xoff, int yoff, std::optional<bool> force_trans = std::nullopt) const {
		auto           cache      = cache_shape();
		unsigned char* transtable = nullptr;
		unsigned char  table[256];
		if (palette_transform != 0) {
			transtable = Get_palette_transform_table(table);
		}
		const Shape_info& info = get_info();
		sman->paint_world_shape(
				xoff, yoff, cache.shape, force_trans ? *force_trans : cache.has_trans,
				transtable, std::max(1, info.get_3d_xtiles(framenum)) * c_tilesize,
				std::max(1, info.get_3d_ytiles(framenum)) * c_tilesize,
				std::max(0, info.get_3d_height()) * c_tilesize / 2);
	}

	// Try the dedicated wall transform for a fixed-scene object. Returning
	// false leaves non-wall IFIX objects on the normal world-sprite path.
	bool paint_world_wall_if_applicable(
			int xoff, int yoff,
			std::optional<bool> force_trans = std::nullopt) const {
		auto           cache      = cache_shape();
		unsigned char* transtable = nullptr;
		unsigned char  table[256];
		if (palette_transform != 0) {
			transtable = Get_palette_transform_table(table);
		}
		if (!cache.shape || !cache.shape->is_rle()) {
			return false;
		}
		const Shape_info& info = get_info();
		const auto wall_profile = iso_wall_profile_for_shape(
				shapenum, framenum, cache.shape->get_width(),
				cache.shape->get_height(), std::max(1, info.get_3d_height()));
		if (!wall_profile) {
			return false;
		}
		sman->paint_world_wall(
				xoff, yoff, cache.shape,
				force_trans ? *force_trans : cache.has_trans, transtable,
				*wall_profile);
		return true;
	}

	void paint_shape_scaled(int xoff, int yoff, int scale, std::optional<bool> force_trans = std::nullopt) const {
		auto           cache      = cache_shape();
		unsigned char* transtable = nullptr;
		unsigned char  table[256];
		if (palette_transform != 0) {
			transtable = Get_palette_transform_table(table);
		}
		sman->paint_shape_scaled(xoff, yoff, scale, cache.shape, force_trans ? *force_trans : cache.has_trans, transtable);
	}

	void paint_invisible(int xoff, int yoff) const {
		sman->paint_invisible(xoff, yoff, get_shape());
	}

	// Paint outline around a shape.
	inline void paint_outline(int xoff, int yoff, Pixel_colors pix) const {
		sman->paint_outline(xoff, yoff, get_shape(), pix);
	}

	void paint_world_tile(int xoff, int yoff, std::optional<bool> force_trans = std::nullopt) const {
		auto           cache      = cache_shape();
		unsigned char* transtable = nullptr;
		unsigned char  table[256];
		if (palette_transform != 0) {
			transtable = Get_palette_transform_table(table);
		}
		if (!cache.shape || !cache.shape->is_rle()) {
			sman->paint_world_tile(
					xoff, yoff, cache.shape,
					force_trans ? *force_trans : cache.has_trans, transtable);
			return;
		}
		const Shape_info& info = get_info();
		const auto wall_profile = iso_wall_profile_for_shape(
				shapenum, framenum, cache.shape->get_width(),
				cache.shape->get_height(), std::max(1, info.get_3d_height()));
		if (!wall_profile) {
			sman->paint_world_tile(
					xoff, yoff, cache.shape,
					force_trans ? *force_trans : cache.has_trans, transtable,
					std::max(1, info.get_3d_xtiles(framenum)) * c_tilesize,
					std::max(1, info.get_3d_ytiles(framenum)) * c_tilesize,
					std::max(0, info.get_3d_height()) * c_tilesize / 2);
			return;
		}
		sman->paint_world_wall(
				xoff, yoff, cache.shape, force_trans ? *force_trans : cache.has_trans,
				transtable, *wall_profile);
	}

	int  get_num_frames() const;
	bool is_frame_empty() const;

	const Shape_info& get_info() const {    // Get info. about shape.
		return Shape_manager::instance->shapes.get_info(shapenum);
	}

	Shape_info& get_info() {    // Get info. about shape.
		return Shape_manager::instance->shapes.get_info(shapenum);
	}

	static Shape_info& get_info(int shnum) {    // Get info. about shape.
		return Shape_manager::instance->shapes.get_info(shnum);
	}

	uint8* Get_palette_transform_table(uint8 table[256]) const;
};

/*
 *  An interface used in Get_click(): This will be painted on top of everything
 * else
 */
class Paintable {
public:
	virtual void paint() = 0;
	virtual ~Paintable() = default;
};

// A paintable that should be painted as a background and not on top of
// everything.
class BackgroundPaintable : public Paintable {};

class ImageBufferPaintable : public BackgroundPaintable {
	std::unique_ptr<Image_buffer> buffer;
	int                           x, y;

public:
	// Construct from an existing Image_buffer
	ImageBufferPaintable(std::unique_ptr<Image_buffer>&& buffer, int x, int y) : buffer(std::move(buffer)), x(x), y(y) {}

	// Construct from a screenshot of the current screen
	ImageBufferPaintable();

	virtual ~ImageBufferPaintable() = default;
	// Inherited via Paintable
	void paint() override;
};
#endif
