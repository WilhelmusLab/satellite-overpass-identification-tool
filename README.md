# Satellite Overpass Identification Tool

The [Satellite Overpass Identification Tool](https://zenodo.org/record/6475619#.ZBhat-zMJUe) is called to generate a list of satellite times for both Aqua and Terra in the area of interest.

## Usage

Install for general use:
```bash
pipx install --spec "git+https://github.com/wilhelmuslab/satellite-overpass-identification-tool" soit
soit --help
```

Run anywhere:
```bash
pipx run --spec "git+https://github.com/wilhelmuslab/satellite-overpass-identification-tool" soit --help
```

## Historical TLE Database Support

The tool supports running from a historical SQLite TLE database, which is now the
default behavior.

Accepted database locations:

1. Local file path (for example, `/data/tles.sqlite`)
2. Public HTTPS URL (for example, a hosted `.sqlite` file)

Remote HTTP(S) databases are downloaded once and cached locally under:

- `$XDG_CACHE_HOME/soit` when `XDG_CACHE_HOME` is set
- `~/.cache/soit` otherwise

Use `--refresh-historical-tle-db` to force a re-download of a remote database,
even when a cached copy already exists.

Examples:

```bash
# Use default public historical DB (HTTP URL)
soit --startdate 2024-01-01 --enddate 2024-01-05 --lat 40.7128 --lon -74.0060 --csvoutpath ./overpasses.csv

# Use a local historical DB file
soit --historical-tle-db /data/aqua_terra_historical_tles.sqlite --startdate 2024-01-01 --enddate 2024-01-05 --lat 40.7128 --lon -74.0060 --csvoutpath ./overpasses.csv

# Force refresh of a remote historical DB
soit --historical-tle-db https://example.org/aqua_terra_historical_tles.sqlite --refresh-historical-tle-db --startdate 2024-01-01 --enddate 2024-01-05 --lat 40.7128 --lon -74.0060 --csvoutpath ./overpasses.csv
```

If you are using [space-track.org](https://www.space-track.org/auth/createAccount) API mode, credentials can be provided as follows:

1. **Command-line arguments**: Pass `--SPACEUSER` and `--SPACEPSWD` as arguments to `soit`
2. **Environment variables**: Set `SPACEUSER` and `SPACEPSWD` as environment variables:
   ```bash
   export SPACEUSER=your@email.com
   export SPACEPSWD=yourpassword
   ```
3. **`.netrc` file**: Add an entry for `space-track.org` to your `~/.netrc` file:
   ```
   machine space-track.org
   login your@email.com
   password yourpassword
   ```

   Ensure the file only has read permissions for the user by calling
   ```bash
   chmod og-rw ~/.netrc
   ```

To use API mode from the executable (instead of the default historical DB
mode), set `--domain`/`-d`:

```bash
soit \
  --domain www.space-track.org \
  --startdate 2024-01-01 \
  --enddate 2024-01-05 \
  --lat 40.7128 \
  --lon -74.0060 \
  --csvoutpath ./overpasses_spacetrack.csv
```