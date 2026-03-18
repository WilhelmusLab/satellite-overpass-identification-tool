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

Your [space-track.org](https://www.space-track.org/auth/createAccount) credentials can be provided as follows:

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

   Meaningless change