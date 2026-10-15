# Publishing this Phase 1 package to GitHub

Suggested repository name: **`wattwitness-microgrid-data-trust`**.

Before choosing Public visibility, confirm permission to redistribute the two files in `data/` (see `data/README.md`). They retain PV/wind values from a supplied simulation export, so derived files are not automatically free of source-data restrictions. The original base export is not included.

## Upload with Git

1. Create an empty GitHub repository named `wattwitness-microgrid-data-trust`. Do not add a second README or license during creation.
2. Unzip this package and open a terminal in the project folder.
3. Run the following commands, replacing `<your-account>` with the account name:

```bash
git init
git add .
git commit -m "Publish WattWitness Phase 1 prototype"
git branch -M main
git remote add origin https://github.com/<your-account>/wattwitness-microgrid-data-trust.git
git push -u origin main
```

4. Check that the dataset, source files, dashboard, reports and README appear on GitHub. The repository is not uploaded by this ZIP itself.

## Run after cloning

```bash
pip install -r requirements.txt
python app.py
python -m unittest discover -s tests -v
```
