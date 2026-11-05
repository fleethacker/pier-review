import formation from './stock/formation.jpg';
import carrier from './stock/carrier.jpg';
import destroyer from './stock/destroyer.jpg';
import frigate from './stock/frigate.jpg';
import replenish from './stock/replenish.jpg';
import submarine from './stock/submarine.jpg';
import helo from './stock/helo.jpg';
import jet from './stock/jet.jpg';
import uav from './stock/uav.jpg';
import launch from './stock/launch.jpg';
import burning from './stock/burning.jpg';
import bridge from './stock/bridge.jpg';
import satellite from './stock/satellite.jpg';
import type { EventType } from './sim';
import type { ClassId } from './types';

/**
 * A small library of pictures to hang on storyboard moments, so a storyboard can be put together without hunting for
 * imagery first. Every one is a public-domain photograph (mostly United States Navy work, which is public domain as a work
 * of the federal government) taken from Wikimedia Commons; `source` records where each came from. They are illustrative
 * stock, not pictures of the exercise being simulated: capture the map or load your own for that.
 */

export type StockId =
  | 'formation'
  | 'carrier'
  | 'destroyer'
  | 'frigate'
  | 'replenish'
  | 'submarine'
  | 'helo'
  | 'jet'
  | 'uav'
  | 'launch'
  | 'burning'
  | 'bridge'
  | 'satellite';

export interface StockPicture {
  id: StockId;
  /** What it shows, for the picker. */
  label: string;
  /** Address of the image file, hashed and emitted by the build. */
  url: string;
  /** Unit classes it suits. */
  classes: ClassId[];
  /** Kinds of event it suits. */
  events: EventType[];
  source: { title: string; page: string; license: string; credit: string };
}

export const STOCK: StockPicture[] = [
  {
    id: 'formation',
    label: 'Strike group in formation',
    url: formation,
    classes: ['CVN'],
    events: [],
    source: {
      title: 'Aerial bow view of George Washington Carrier Strike Group in formation for photo exercise 060429-N-9621S-014',
      page: 'https://commons.wikimedia.org/wiki/File:Aerial_bow_view_of_George_Washington_Carrier_Strike_Group_in_formation_for_photo_exercise_060429-N-9621S-014.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Photographer\'s Mate 3rd Class Christopher Stephens',
    },
  },
  {
    id: 'carrier',
    label: 'Carrier seen from above',
    url: carrier,
    classes: ['CVN'],
    events: [],
    source: {
      title: 'USS Ticonderoga (CVS-14) underway at sea, circa 29 April 1972',
      page: 'https://commons.wikimedia.org/wiki/File:USS_Ticonderoga_(CVS-14)_underway_at_sea,_circa_29_April_1972.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy',
    },
  },
  {
    id: 'destroyer',
    label: 'Destroyer in a heavy sea',
    url: destroyer,
    classes: ['DDG', 'CG'],
    events: [],
    source: {
      title: 'US Navy 050402-N-6363M-027 Waves crash over the bow of the Arleigh-Burke-class guided missile destroyer USS Barry (DDG 52) as she plows through heavy seas while underway in the Mediterranean Sea',
      page: 'https://commons.wikimedia.org/wiki/File:US_Navy_050402-N-6363M-027_Waves_crash_over_the_bow_of_the_Arleigh-Burke-class_guided_missile_destroyer_USS_Barry_(DDG_52)_as_she_plows_through_heavy_seas_while_underway_in_the_Mediterranean_Sea.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Photographer’s Mate Airman Philip V. Morrill',
    },
  },
  {
    id: 'frigate',
    label: 'Frigate underway',
    url: frigate,
    classes: ['FFG'],
    events: [],
    source: {
      title: 'Portugese frigate Almirante Pereira da Silva (F472) underway at sea, in 1972',
      page: 'https://commons.wikimedia.org/wiki/File:Portugese_frigate_Almirante_Pereira_da_Silva_(F472)_underway_at_sea,_in_1972.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy',
    },
  },
  {
    id: 'replenish',
    label: 'Replenishment at sea',
    url: replenish,
    classes: ['CARGO', 'LHD'],
    events: [],
    source: {
      title: 'Flickr - Official U.S. Navy Imagery - A supply ship prepares for underway replenishment.',
      page: 'https://commons.wikimedia.org/wiki/File:Flickr_-_Official_U.S._Navy_Imagery_-_A_supply_ship_prepares_for_underway_replenishment..jpg',
      license: 'Public domain',
      credit: 'Official Navy Page from United States of America MC3 Randy J. Savarese/U.S. Navy',
    },
  },
  {
    id: 'submarine',
    label: 'Submarine on the surface',
    url: submarine,
    classes: ['SSN', 'SSK'],
    events: ['detected'],
    source: {
      title: 'A port bow view of the US Navy (USN) LOS ANGELES CLASS- Attack Submarine USS ALBUQUERQUE (SSN 706), underway in the Atlantic Ocean, while participating in Exercise MAJESTIC EAGLE 20 - DPLA - cd72cc6879754214027b11472a72fa7d',
      page: 'https://commons.wikimedia.org/wiki/File:A_port_bow_view_of_the_US_Navy_(USN)_LOS_ANGELES_CLASS-_Attack_Submarine_USS_ALBUQUERQUE_(SSN_706),_underway_in_the_Atlantic_Ocean,_while_participating_in_Exercise_MAJESTIC_EAGLE_20_-_DPLA_-_cd72cc6879754214027b11472a72fa7d.jpeg',
      license: 'Public domain',
      credit: 'Department of Defense. American Forces Information Service. Defense Visual Information Center. 1994',
    },
  },
  {
    id: 'helo',
    label: 'Helicopter over the water',
    url: helo,
    classes: ['HELO'],
    events: [],
    source: {
      title: 'US Navy 061201-N-6423H-004 A U.S. Coast Guard HH-60 Jayhawk helicopter attempts to lower a submersible water pump to the crew of the fishing vessel Miss Melissa',
      page: 'https://commons.wikimedia.org/wiki/File:US_Navy_061201-N-6423H-004_A_U.S._Coast_Guard_HH-60_Jayhawk_helicopter_attempts_to_lower_a_submersible_water_pump_to_the_crew_of_the_fishing_vessel_Miss_Melissa.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Mass Communication Specialist 1st Class Erik Hoffmann',
    },
  },
  {
    id: 'jet',
    label: 'Jet launching from a carrier',
    url: jet,
    classes: ['FIGHTER', 'AEW'],
    events: [],
    source: {
      title: 'Flickr - Official U.S. Navy Imagery - A jet launches from the flight deck. (10)',
      page: 'https://commons.wikimedia.org/wiki/File:Flickr_-_Official_U.S._Navy_Imagery_-_A_jet_launches_from_the_flight_deck._(10).jpg',
      license: 'Public domain',
      credit: 'Official Navy Page from United States of America MC2 James R. Evans/U.S. Navy',
    },
  },
  {
    id: 'uav',
    label: 'Drone away',
    url: uav,
    classes: ['UAV', 'DRONE'],
    events: ['launch'],
    source: {
      title: 'US Navy 060508-N-4021H-066 A Manta Unmanned Aerial Vehicle (UAV) launches from the flight deck of experimental boat ship Stiletto during Exercise Howler',
      page: 'https://commons.wikimedia.org/wiki/File:US_Navy_060508-N-4021H-066_A_Manta_Unmanned_Aerial_Vehicle_(UAV)_launches_from_the_flight_deck_of_experimental_boat_ship_Stiletto_during_Exercise_Howler.jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Photographer\'s Mate Airman Damien Horvath',
    },
  },
  {
    id: 'launch',
    label: 'Missile launch at night',
    url: launch,
    classes: ['ASM', 'SAM', 'TORP'],
    events: ['launch', 'intercept'],
    source: {
      title: 'US Navy 030320-N-6141B-003 Tomahawk Land Attack Missiles (TLAM) launch from the ship\'s forward and aft MK-41 vertical launch systems (VLS) aboard the guided missile destroyer USS Donald Cook (DDG 75)',
      page: 'https://commons.wikimedia.org/wiki/File:US_Navy_030320-N-6141B-003_Tomahawk_Land_Attack_Missiles_(TLAM)_launch_from_the_ship%27s_forward_and_aft_MK-41_vertical_launch_systems_(VLS)_aboard_the_guided_missile_destroyer_USS_Donald_Cook_(DDG_75).jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Chief Journalist Alan J. Baribeau.',
    },
  },
  {
    id: 'burning',
    label: 'Fire and damage control',
    url: burning,
    classes: [],
    events: ['hit', 'destroyed', 'mine'],
    source: {
      title: 'USS IWO JIMA DAMAGE CONTROL DRILL (8933537)',
      page: 'https://commons.wikimedia.org/wiki/File:USS_IWO_JIMA_DAMAGE_CONTROL_DRILL_(8933537).jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Seaman Brendan Watt',
    },
  },
  {
    id: 'bridge',
    label: 'Bridge watch',
    url: bridge,
    classes: [],
    events: ['detected', 'held'],
    source: {
      title: 'US Navy 030212-N-8935H-001 The watch repeats a message on the port bridge wing of the amphibious command ship USS Blue Ridge (LCC 19)',
      page: 'https://commons.wikimedia.org/wiki/File:US_Navy_030212-N-8935H-001_The_watch_repeats_a_message_on_the_port_bridge_wing_of_the_amphibious_command_ship_USS_Blue_Ridge_(LCC_19).jpg',
      license: 'Public domain',
      credit: 'U.S. Navy photo by Photographer\'s Mate 2nd Class Edward L Holland.',
    },
  },
  {
    id: 'satellite',
    label: 'The sea from orbit',
    url: satellite,
    classes: [],
    events: [],
    source: {
      title: 'Cloud Streets Over the Laptev Sea (154559)',
      page: 'https://commons.wikimedia.org/wiki/File:Cloud_Streets_Over_the_Laptev_Sea_(154559).jpg',
      license: 'Public domain',
      credit: 'NASA Earth Observatory image by Michala Garrison, using MODIS data from NASA EOSDIS LANCE and GIBS/W',
    },
  },
];

const byId = new Map(STOCK.map((s) => [s.id, s]));

export const stockById = (id: string): StockPicture | undefined => byId.get(id as StockId);

/** Is this picture one of ours, rather than a captured or loaded one? */
export const isStock = (url: string | undefined): boolean => !!url && STOCK.some((s) => s.url === url);

export const stockByUrl = (url: string | undefined): StockPicture | undefined => STOCK.find((s) => s.url === url);

/**
 * The picture that best fits a beat: one that matches the kind of event first, then the class of unit it hangs on, so a
 * destroyed ship gets the fire and a submarine contact gets the submarine.
 */
export function pickStock(event: EventType | undefined, classId: ClassId | undefined): StockPicture | undefined {
  if (event) {
    const byEvent = STOCK.filter((s) => s.events.includes(event));
    // Prefer one that also matches the unit, so a destroyed aircraft does not get a burning ship if something fits better.
    const both = byEvent.find((s) => classId && s.classes.includes(classId));
    if (both) return both;
    if (byEvent.length) return byEvent[0];
  }
  if (classId) {
    const byClass = STOCK.find((s) => s.classes.includes(classId));
    if (byClass) return byClass;
  }
  return undefined;
}

/** The stock pictures by name, for scenarios that ship with a storyboard. */
export const stock = Object.fromEntries(STOCK.map((s) => [s.id, s.url])) as Record<StockId, string>;
