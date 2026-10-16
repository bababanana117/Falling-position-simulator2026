// Display-only EGM96 geoid offset, in metres above the WGS84 ellipsoid.
// NGA public-domain data; format/reference attribution: ../data/README.md.
// This is an independent bilinear sampler, not a conversion of flight state.
const ROWS = 721;
const COLUMNS = 1440;
const BYTES = ROWS * COLUMNS * 2;

/**
 * Read the headerless WW15MGH.DAC signed, big-endian centimetre grid.
 * The caller loads the pinned local asset; this function performs no I/O.
 * A private copy prevents later mutation/detachment of the caller's buffer
 * from changing the datum used by an already displayed trajectory.
 *
 * @param {ArrayBuffer} buffer Exactly 2,076,480 bytes.
 * @returns {{heightOffset: (lonDeg: number, latDeg: number) => number}}
 */
export function parseEgm96(buffer) {
  if (!(buffer instanceof ArrayBuffer)) {
    throw new TypeError('EGM96 requires an ArrayBuffer.');
  }
  if (buffer.byteLength !== BYTES) {
    throw new RangeError(`EGM96 requires exactly ${BYTES} bytes.`);
  }
  const data = new DataView(buffer.slice(0));
  const node = (row, column) => data.getInt16((row * COLUMNS + column) * 2, false);
  // All longitudes represent the same point at a pole. Reject a malformed
  // polar row instead of making its displayed height depend on longitude.
  for (const row of [0, ROWS - 1]) {
    const polarHeight = node(row, 0);
    for (let column = 1; column < COLUMNS; column++) {
      if (node(row, column) !== polarHeight) {
        throw new RangeError('EGM96 polar rows must be constant.');
      }
    }
  }

  return Object.freeze({
    heightOffset(lonDeg, latDeg) {
      if (!Number.isFinite(lonDeg) || !Number.isFinite(latDeg)) {
        throw new TypeError('EGM96 longitude and latitude must be finite numbers.');
      }
      if (latDeg < -90 || latDeg > 90) {
        throw new RangeError('EGM96 latitude must be within [-90, 90] degrees.');
      }
      if (latDeg === 90) return node(0, 0) / 100;
      if (latDeg === -90) return node(ROWS - 1, 0) / 100;

      // Longitude is periodic. In particular, the eastern neighbour of
      // 359.75 degrees is column 0 of THE SAME row, never the next row.
      let longitude = lonDeg % 360;
      if (longitude < 0) longitude += 360;
      const x = (longitude * 4) % COLUMNS;
      const y = (90 - latDeg) * 4;
      const west = Math.floor(x);
      const east = (west + 1) % COLUMNS;
      const north = Math.min(ROWS - 1, Math.floor(y));
      const south = Math.min(ROWS - 1, north + 1);
      const dx = x - west;
      const dy = y - north;
      const upper = node(north, west) * (1 - dx) + node(north, east) * dx;
      const lower = node(south, west) * (1 - dx) + node(south, east) * dx;
      return (upper * (1 - dy) + lower * dy) / 100;
    },
  });
}
