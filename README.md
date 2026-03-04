# Satellite Overpass Identification Tool

The [Satellite Overpass Identification Tool](https://zenodo.org/record/6475619#.ZBhat-zMJUe) is called to generate a list of satellite times for both Aqua and Terra in the area of interest.

## Credentials

Your [space-track.org](https://www.space-track.org/auth/createAccount) credentials can be provided in two ways:

1. **Command-line arguments**: Pass `--SPACEUSER` and `--SPACEPSWD` directly.
2. **`.netrc` file**: Add an entry for `space-track.org` to your `~/.netrc` file:
   ```
   machine space-track.org
   login your@email.com
   password yourpassword
   ```
   When `--SPACEUSER` or `--SPACEPSWD` are not provided, the tool will automatically look up credentials from `~/.netrc`.
   
   Ensure the file only has read permissions for the user by calling 
   ```bash
   chmod og-rw ~/.netrc
   ```

## Run the code

You can run the local version of the code from this directory by calling
```bash
pipx run . soit
```

You can run the code anywhere by calling:
```bash
pipx run --spec "git+https://github.com/wilhelmuslab/ice-floe-tracker-pipeline#egg=satellite-overpass-identification-tool&subdirectory=satellite-overpass-identification-tool" soit
```

You can run the Docker image by calling:
```bash
docker run -it brownccv/icefloetracker-soit
```
