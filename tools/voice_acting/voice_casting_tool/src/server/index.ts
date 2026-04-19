import express from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { parse } from 'csv-parse/sync';
import dotenv from 'dotenv';

import npcsRouter from './routes/npcs.js';
import voicesRouter from './routes/voices.js';
import assignmentsRouter from './routes/assignments.js';
import bookmarksRouter from './routes/bookmarks.js';
import generateRouter from './routes/generate.js';
import wikiRouter from './routes/wiki.js';
import suggestionsRouter from './routes/suggestions.js';
import voiceWavsRouter from './routes/voiceWavs.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env from voice_acting directory
dotenv.config({ path: path.join(__dirname, '../../../.env') });

const app = express();
app.use(cors());
app.use(express.json());

// Manifest CSV path. Set MANIFEST_CSV in .env to point elsewhere; falls back
// to the default in the voice_acting dir.
const manifestPath = process.env.MANIFEST_CSV
  ? path.resolve(process.env.MANIFEST_CSV)
  : path.join(__dirname, '../../../csvs/manifest.csv');
if (!fs.existsSync(manifestPath)) {
  console.error(`\nERROR: manifest CSV not found at ${manifestPath}`);
  console.error('Run `python prepare_voice_lines.py` from the voice_acting dir to');
  console.error('generate one, or set MANIFEST_CSV in .env to point at an existing file.\n');
  process.exit(1);
}
const manifestRaw = fs.readFileSync(manifestPath, 'utf-8');
const manifestRows = parse(manifestRaw, { columns: true, skip_empty_lines: true });

// Voice WAV directory. Optional - when unset, the "play from disk" UI is
// disabled. Used by the /api/voice-wavs/... routes.
export const VOICE_WAV_DIR = process.env.VOICE_WAV_DIR
  ? path.resolve(process.env.VOICE_WAV_DIR) : null;

// City map for NPCs
const CITY_MAP: Record<string, string> = {
  "Iolo": "Party", "Spark": "Party", "Shamino": "Party", "Dupre": "Party",
  "Jaana": "Party", "Sentri": "Party", "Julia": "Party", "Katrina": "Party",
  "Tseramed": "Party",
  "Petre": "Trinsic", "Finnigan": "Trinsic", "Gilberto": "Trinsic",
  "Johnson": "Trinsic", "Klog": "Trinsic", "Chantu": "Trinsic",
  "Dell": "Trinsic", "Apollonia": "Trinsic", "Markus": "Trinsic",
  "Gargan": "Trinsic", "Caroline": "Trinsic", "Ellen": "Trinsic",
  "Guard": "Trinsic", "Paul": "Trinsic", "Meryl": "Trinsic", "Dustin": "Trinsic",
  "Lord British": "Britain", "Nystul": "Britain", "Chuckles": "Britain",
  "Batlin": "Britain", "Patterson": "Britain", "Geoffrey": "Britain",
  "Raymundo": "Britain", "Jesse": "Britain", "Stuart": "Britain",
  "Amber": "Britain", "Coop": "Britain", "Grayson": "Britain",
  "Willy": "Britain", "Gaye": "Britain", "Lucy": "Britain",
  "Greg": "Britain", "Fred": "Britain", "Kelly": "Britain",
  "Sean": "Britain", "Gordon": "Britain", "Clint": "Britain",
  "Diane": "Britain", "James": "Britain", "Jeanette": "Britain",
  "Brownie": "Britain", "Mack": "Britain", "Snaz": "Britain",
  "Millie": "Britain", "Candice": "Britain", "Cynthia": "Britain",
  "Carrocio": "Britain", "Figg": "Britain", "Neno": "Britain",
  "Judith": "Britain", "Denby": "Britain", "Kessler": "Britain",
  "Miranda": "Britain", "Nell": "Britain", "Charles": "Britain",
  "Boots": "Britain", "Bennie": "Britain", "Weston": "Britain",
  "Csil": "Britain", "Zella": "Britain", "Nanna": "Britain",
  "Kristy": "Britain", "Max": "Britain", "Nicholas": "Britain",
  "Wislem": "Britain", "Sherry": "Britain", "Inwisloklem": "Britain",
  "Rudyom": "Cove", "Nastassia": "Cove", "Rayburt": "Cove",
  "Lord Heather": "Cove", "Pamela": "Cove", "Zinaida": "Cove", "De Maria": "Cove",
  "Elynor": "Minoc", "Gregor": "Minoc", "Margareta": "Minoc",
  "Sasha": "Minoc", "Gladstone": "Minoc", "Xanthia": "Minoc",
  "Zorn": "Minoc", "Seara": "Minoc", "Karl": "Minoc",
  "Owen": "Minoc", "Burnside": "Minoc", "Rutherford": "Minoc",
  "William": "Minoc", "Karenna": "Minoc", "Jakher": "Minoc",
  "Mikos": "Minoc", "Fodus": "Minoc", "Owings": "Minoc",
  "Malloy": "Minoc", "Jergi": "Minoc",
  "Trellek": "Yew", "Saralek": "Yew", "Tavenor": "Yew",
  "Salamon": "Yew", "Nicodemus": "Yew", "Thad": "Yew",
  "Bradman": "Yew", "Sir Jeff": "Yew", "Tiery": "Yew",
  "Reyna": "Yew", "Perrin": "Yew", "Taylor": "Yew",
  "Aimi": "Yew", "Penni": "Yew", "Ben": "Yew", "Goth": "Yew",
  "Kreg": "Yew", "Smith": "Yew", "Papa": "Yew", "Mama": "Yew",
  "De Snel": "Jhelom", "Joseph": "Jhelom", "Kliftin": "Jhelom",
  "Ophelia": "Jhelom", "Daphne": "Jhelom", "Sprellic": "Jhelom",
  "Vokes": "Jhelom", "Syria": "Jhelom", "Timmons": "Jhelom",
  "Russell": "New Magincia", "Boris": "New Magincia",
  "Magenta": "New Magincia", "Henry": "New Magincia",
  "Constance": "New Magincia", "Robin": "New Magincia",
  "Battles": "New Magincia", "Leavell": "New Magincia",
  "Sam": "New Magincia", "Alagner": "New Magincia",
  "Markham": "Skara Brae", "Horance": "Skara Brae",
  "Trent": "Skara Brae", "Mordra": "Skara Brae",
  "Rowena": "Skara Brae", "Paulette": "Skara Brae",
  "Quenton": "Skara Brae", "Forsythe": "Skara Brae", "Caine": "Skara Brae",
  "Carlyn": "Moonglow", "Penumbra": "Moonglow", "Zelda": "Moonglow",
  "Mariah": "Moonglow", "Cubolt": "Moonglow", "Balayna": "Moonglow",
  "Tolemac": "Moonglow", "Morz": "Moonglow", "Jillian": "Moonglow",
  "Effrem": "Moonglow", "Chad": "Moonglow", "Elad": "Moonglow",
  "Phearcy": "Moonglow", "Addom": "Moonglow", "Frank": "Moonglow",
  "Brion": "Moonglow", "Nelson": "Moonglow", "Rankin": "Moonglow",
  "Thurston": "Paws", "Feridwyn": "Paws", "Brita": "Paws",
  "Alina": "Paws", "Merrick": "Paws", "Garritt": "Paws",
  "Morfin": "Paws", "Beverlea": "Paws", "Komor": "Paws",
  "Fenn": "Paws", "Andrew": "Paws", "Camille": "Paws",
  "Tobias": "Paws", "Polly": "Paws",
  "Draxinusom": "Terfin", "Inforlem": "Terfin", "Inmanilem": "Terfin",
  "Teregus": "Terfin", "Runeb": "Terfin", "Quan": "Terfin",
  "Quaeven": "Terfin", "Silamo": "Terfin", "Sarpling": "Terfin",
  "Forbrak": "Terfin", "Betra": "Terfin",
  "Menion": "Serpent's Hold", "Pendaran": "Serpent's Hold",
  "Jehanne": "Serpent's Hold", "John Paul": "Serpent's Hold",
  "Richter": "Serpent's Hold", "Horffe": "Serpent's Hold",
  "Jordan": "Serpent's Hold", "Denton": "Serpent's Hold",
  "Tory": "Serpent's Hold", "Leigh": "Serpent's Hold",
  "Cador": "Vesper", "Mara": "Vesper", "Zaksam": "Vesper",
  "Eldroth": "Vesper", "Yongi": "Vesper", "Blorn": "Vesper",
  "Auston": "Vesper", "Liana": "Vesper", "Lap Lem": "Vesper",
  "Yvella": "Vesper", "Catherine": "Vesper", "For Lem": "Vesper",
  "Ansikart": "Vesper", "Wis Sur": "Vesper", "Anmanivas": "Vesper",
  "Foranamo": "Vesper", "Aurvidlem": "Vesper",
  "Sullivan": "Buccaneer's Den", "Wench": "Buccaneer's Den",
  "Glenno": "Buccaneer's Den", "Martine": "Buccaneer's Den",
  "Roberto": "Buccaneer's Den", "Sintag": "Buccaneer's Den",
  "Blacktooth": "Buccaneer's Den", "Mole": "Buccaneer's Den",
  "Lucky": "Buccaneer's Den", "Budo": "Buccaneer's Den",
  "Gordy": "Buccaneer's Den", "Mandy": "Buccaneer's Den",
  "Smithy": "Buccaneer's Den", "Danag": "Buccaneer's Den",
  "Grod": "Buccaneer's Den", "Anton": "Buccaneer's Den",
  "Erethian": "Forge of Virtue", "Arcadion": "Forge of Virtue",
  "Dracothraxus": "Forge of Virtue", "Bollux": "Forge of Virtue",
  "Adjhar": "Forge of Virtue", "Dark Core": "Forge of Virtue",
  "Time Lord": "Forge of Virtue", "Ferryman": "Forge of Virtue",
  "Stone Guardian": "Forge of Virtue", "Shrine": "Forge of Virtue",
  "Guardian": "Endgame", "Hook": "Endgame", "Forskis": "Endgame",
  "Abraham": "Endgame", "Elizabeth": "Endgame",
  "Shandu": "Ambrosia", "Shanda": "Ambrosia", "Shando": "Ambrosia",
  "Kissme": "Ambrosia",
  "Eiko": "Dagger Isle", "Amanda": "Dagger Isle", "Iskander": "Dagger Isle",
  "Iriale": "Fellowship Retreat", "Ian": "Fellowship Retreat", "Gorn": "Fellowship Retreat",
  "Wayne": "Dungeon", "Garok": "Dungeon", "Gharl": "Dungeon",
  "D Rel": "Dungeon", "Cairbre": "Dungeon", "Kallibrus": "Dungeon",
  "Cosmo": "Dungeon", "Lasher": "Dungeon", "Xorinia": "Dungeon",
  "Martingo": "Spektran",
};

// Portrait files mapping
const PORTRAIT_FILES: Record<string, string> = {
  "Abraham": "Abraham.png", "Addom": "AddomU7.PNG", "Adjhar": "AdjharU7.png",
  "Aimi": "AimiU7.PNG", "Alagner": "Alagner.PNG", "Alina": "AlinaU7.PNG",
  "Amanda": "AmandaU7.PNG", "Amber": "Amber.gif", "Andrew": "Andrew.gif",
  "Anmanivas": "Anmanivas.gif", "Ansikart": "Ansikart.gif", "Anton": "Anton.gif",
  "Apollonia": "Apollonia.gif", "Arcadion": "ArcadionU7.png",
  "Aurvidlem": "Aurvidlem.gif", "Auston": "Auston.gif", "Balayna": "BalaynaU7.png",
  "Batlin": "Batlin.gif", "Battles": "Battles.gif", "Ben": "BenU7.png",
  "Bennie": "Bennie.PNG", "Betra": "Betra.gif", "Beverlea": "Beverlea.gif",
  "Blacktooth": "Blacktooth.gif", "Blorn": "Blorn.jpg", "Bollux": "BolluxU7.png",
  "Boots": "Boots.gif", "Boris": "Boris.gif", "Bradman": "BradmanU7.png",
  "Brion": "BrionU7.png", "Brita": "Brita.PNG", "Lord British": "BritishU7.PNG",
  "Brownie": "Brownie.gif", "Budo": "BudoU7.gif", "Burnside": "BurnsideU7.png",
  "Cador": "Cador.gif", "Caine": "Caine.PNG", "Cairbre": "Cairbre.gif",
  "Camille": "Camille.gif", "Candice": "Candice.gif", "Carlyn": "CarlynU7.png",
  "Caroline": "Caroline.gif", "Carrocio": "Carrocio.gif", "Catherine": "Catherine.gif",
  "Chad": "ChadU7.png", "Chantu": "Chantu.gif", "Charles": "CharlesU7.gif",
  "Chuckles": "Chuckles.gif", "Clint": "Clint.gif", "Constance": "Constance.gif",
  "Coop": "Coop.jpg", "Cosmo": "Cosmo.gif", "Csil": "Csil.gif",
  "Cubolt": "CuboltU7.png", "Cynthia": "Cynthia.jpg", "Danag": "Danag.gif",
  "Daphne": "Daphne.gif", "De Maria": "DeMaria.gif", "De Snel": "DeSnel.gif",
  "Dell": "Dell.gif", "Denby": "Denby.jpg", "Denton": "Denton.gif",
  "Diane": "Diane.jpg", "Dracothraxus": "Dracothraxus.gif",
  "Draxinusom": "Draxinusom.PNG", "Dupre": "DupreU7.PNG", "Dustin": "Dustin.gif",
  "Effrem": "EffremU7.png", "Eiko": "Eiko.gif", "Elad": "EladU7.png",
  "Eldroth": "Eldroth.gif", "Elizabeth": "Elizabeth.png", "Ellen": "Ellen.gif",
  "Elynor": "Elynor.gif", "Erethian": "ErethianU7.png", "Fenn": "Fenn.gif",
  "Feridwyn": "FeridwynU7.png", "Ferryman": "FerrymanU7.png", "Figg": "Figg.gif",
  "Finnigan": "Finnigan.PNG", "Fodus": "FodusU7.png", "For Lem": "Forlem.gif",
  "Foranamo": "Foranamo.gif", "Forbrak": "Forbrak.gif", "Forskis": "Forskis.png",
  "Forsythe": "Forsythe.gif", "Frank": "FranktheFoxU7.png", "Fred": "Fred.jpg",
  "Gargan": "Gargan.gif", "Garok": "Garok.PNG", "Garritt": "Garritt.gif",
  "Gaye": "Gaye.gif", "Geoffrey": "GeoffreyU7.PNG", "Gharl": "GharlU7.png",
  "Gilberto": "Gilberto.gif", "Gladstone": "Gladstone.gif", "Glenno": "Glenno.gif",
  "Gordon": "Gordon.jpg", "Gordy": "Gordy.gif", "Gorn": "Gorn.gif",
  "Goth": "GothU7.png", "Grayson": "Grayson.jpg", "Greg": "Greg.gif", "Guard": "Guard1U7.png",
  "Gregor": "Gregor.gif", "Grod": "Grod.gif", "Lord Heather": "Heather.gif",
  "Henry": "Henry.gif", "Hook": "Hook.png", "Horance": "Horance.png",
  "Horffe": "Horffe.gif", "Shandu": "HydraBrothersU7.png",
  "Shanda": "HydraBrothersU7.png", "Shando": "HydraBrothersU7.png",
  "Ian": "Ian.PNG", "Inforlem": "Inforlem.gif", "Inmanilem": "Inmanilem.gif",
  "Inwisloklem": "Inwisloklem.gif", "Iolo": "IoloU7.png",
  "Iriale": "IrialeSilvermist.PNG", "Iskander": "Iskander.gif",
  "Jaana": "Jaana.gif", "Jakher": "Jakher.gif", "James": "James.jpg",
  "Jeanette": "Jeanette.jpg", "Jehanne": "Jehanne.gif", "Jergi": "Jergi.gif",
  "Jesse": "Jesse.jpg", "Jillian": "JillianU7.png", "John Paul": "JohnPaul.gif",
  "Johnson": "Johnson.gif", "Jordan": "Jordan.gif", "Joseph": "Joseph.gif",
  "Judith": "Judith.gif", "Julia": "JuliaU7.PNG", "Kallibrus": "Kallibrus.gif",
  "Karenna": "Karenna.gif", "Karl": "Karl.gif", "Katrina": "Katrina.gif",
  "Kelly": "Kelly.jpg", "Kessler": "Kessler.gif", "Kissme": "Kissme.png",
  "Kliftin": "Kliftin.PNG", "Klog": "Klog.gif", "Komor": "Komor.gif",
  "Kreg": "KregU7.png", "Kristy": "Kristy.gif", "Lap Lem": "Laplem.gif",
  "Lasher": "Lasher.gif", "Leavell": "Leavell.gif", "Leigh": "Leigh.gif",
  "Liana": "Liana.gif", "Lucky": "Lucky.gif", "Lucy": "Lucy.jpg",
  "Mack": "Mack.gif", "Magenta": "Magenta.gif", "Mandy": "Mandy.gif",
  "Mara": "Mara.gif", "Margareta": "Margareta.PNG", "Mariah": "MariahU7.png",
  "Markham": "Markham.gif", "Markus": "Markus.gif", "Martine": "Martine.gif",
  "Martingo": "Martingo.gif", "Max": "MaxU7.png", "Menion": "Menion.gif",
  "Merrick": "Merrick.gif", "Meryl": "Meryl.PNG", "Mikos": "Mikos.gif",
  "Millie": "Millie.gif", "Miranda": "MirandaU7.PNG", "Mole": "Mole.gif",
  "Mordra": "Mordra.gif", "Morfin": "Morfin.PNG", "Morz": "MorzU7.png",
  "Nanna": "NannaU7.gif", "Nastassia": "Nastassia.gif", "Nell": "NellU7.gif",
  "Nelson": "NelsonU7.png", "Neno": "Neno.gif", "Nicholas": "Nicholas.gif",
  "Nicodemus": "NicodemusU7.png", "Nystul": "NystulU7.PNG", "Ophelia": "Ophelia.gif",
  "Owen": "Owen.gif", "Owings": "MalOw.gif", "Pamela": "Pamela.gif",
  "Patterson": "PattersonU7.PNG", "Paul": "Paul.gif", "Paulette": "Paulette.gif",
  "Pendaran": "Pendaran.gif", "Penni": "PenniU7.png", "Penumbra": "PenumbraU7.png",
  "Perrin": "PerrinU7.png", "Petre": "Petre.gif", "Phearcy": "PhearcyU7.png",
  "Polly": "Polly.gif", "Quaeven": "Quaeven.gif", "Quan": "Quan.gif",
  "Quenton": "Quenton.gif", "Rankin": "RankinU7.png", "Rayburt": "Rayburt.gif",
  "Raymundo": "RaymundoU7.png", "Reyna": "ReynaU7.png", "Richter": "Richter.gif",
  "Roberto": "Roberto.gif", "Robin": "Robin.gif", "Rowena": "Rowena.gif",
  "Rudyom": "Rudyom.gif", "Runeb": "Runeb.PNG", "Russell": "Russell.PNG",
  "Rutherford": "Rutherford.gif", "Salamon": "Salamon.gif", "Sam": "Sam.gif",
  "Saralek": "Saralek.gif", "Sarpling": "Sarpling.gif", "Sasha": "Sasha.gif",
  "Sean": "Sean.jpg", "Seara": "Seara.gif", "Sentri": "SentriU7.PNG",
  "Shamino": "ShaminoU7.PNG", "Sherry": "Sherry.gif", "Silamo": "Silamo.gif",
  "Sintag": "Sintag.PNG", "Sir Jeff": "SirJeff.gif", "Smith": "Smith.gif",
  "Smithy": "Smithy.gif", "Snaz": "Snaz.gif", "Spark": "Spark.gif",
  "Sprellic": "Sprellic.gif", "Stuart": "Stuart.jpg", "Sullivan": "Sullivan.gif",
  "Syria": "SyriaU7.gif", "Tavenor": "Tavenor.gif", "Taylor": "Taylor.gif",
  "Teregus": "Teregus.gif", "Thad": "Thad.gif", "Thurston": "Thurston.gif",
  "Tiery": "Tiery.gif", "Time Lord": "Timelord.gif", "Timmons": "Timmons.gif",
  "Tobias": "Tobias.gif", "Tolemac": "TolemacU7.png", "Tory": "ToryU7.PNG",
  "Trellek": "Trellek.gif", "Trent": "Trent.gif", "Tseramed": "Tseramed.gif",
  "Vokes": "Vokes.gif", "Wayne": "Wayne.gif", "Wench": "Wench.gif",
  "Weston": "Weston.gif", "William": "William.gif", "Willy": "Willy.gif",
  "Wislem": "Wislem.gif", "Wis Sur": "WisSur.gif", "Xanthia": "Xanthia.gif",
  "Xorinia": "XoriniaWispU7.png", "Yongi": "Yongi.gif", "Yvella": "Yvella.gif",
  "Zaksam": "Zaksam.gif", "Zelda": "ZeldaU7.png", "Zella": "Zella.PNG",
  "Zinaida": "Zinaida.PNG", "Zorn": "ZornNPC.PNG",
};

// Build NPC index from manifest
interface ManifestLine {
  speaker: string;
  text: string;
  filename: string;
  offset_key: string;
  segment: string;
  voice_id?: string;
  voice_desc?: string;
  func_id?: string;
}

const npcLines: Record<string, ManifestLine[]> = {};
for (const row of manifestRows as ManifestLine[]) {
  if (row.speaker) {
    if (!npcLines[row.speaker]) npcLines[row.speaker] = [];
    npcLines[row.speaker].push(row);
  }
}

// Export data for routes
export { npcLines, CITY_MAP, PORTRAIT_FILES };

// Serve portrait images
app.use('/portraits', express.static(path.join(__dirname, '../../data/portraits')));

// Serve generated audio
app.use('/generated', express.static(path.join(__dirname, '../../generated')));

// API routes
app.use('/api/npcs', npcsRouter);
app.use('/api/voices', voicesRouter);
app.use('/api/assignments', assignmentsRouter);
app.use('/api/bookmarks', bookmarksRouter);
app.use('/api/generate', generateRouter);
app.use('/api/wiki', wikiRouter);
app.use('/api/suggestions', suggestionsRouter);
app.use('/api/voice-wavs', voiceWavsRouter);

const PORT = 3001;
app.listen(PORT, () => {
  console.log(`Voice Casting API running at http://localhost:${PORT}`);
  console.log(`Loaded ${Object.keys(npcLines).length} NPCs with ${manifestRows.length} lines`);
});
