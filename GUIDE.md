# Keeping JW Library in step across your devices

This guide is for using jwsync, not for developing it. You do not need to know
anything about programming.

## What it does

JW Library keeps your notes, highlights, bookmarks, tags and playlists on one
device at a time. It can make a backup and it can restore one — but restoring
**replaces** everything already on that device, so you cannot simply restore
your phone's backup onto your tablet without losing whatever the tablet had.

jwsync merges those backups instead. It takes what is on your phone, your tablet
and your computer, combines them into one library that has everything, and gives
you a single file to restore everywhere.

Nothing you have is deleted. Nothing leaves your computer.

## Before you start

**Keep your original backups** until you have checked that the merged one looks
right. jwsync never changes them — it only writes new files — so they are your
way back if anything looks wrong.

## Two ways to do this

**If you have an iPad or iPhone and no computer** — or you simply do not want to
install anything — use the web page. It runs entirely inside your browser, on
your own device. Your backups are never uploaded anywhere. Skip to
[Using the web page](#using-the-web-page).

**If you have a Mac or a PC**, the app version can also read and write JW
Library on that computer directly, which removes two of the steps there. Carry
on reading below.

## Using the web page

### The first time

1. Open the page (your congregation's link, or the `jwsync.html` file if someone
   sent you one).
2. On **each** device: JW Library ▸ **Personal Study** ▸ the **⤒** icon ▸
   **Create Backup**, and save it to Files.
3. On the page, tap **Choose backup files** and pick all of them.
4. Tap **Combine**. It tells you when it is done and confirms that every note,
   highlight, bookmark, tag and playlist was found in the result.
5. Tap **Save the combined file** and save it to Files.
6. On each device: **Personal Study ▸ ⤒ ▸ Restore Backup**, and pick that file.

### Every time after that

The page remembers your combined library, so you only need a fresh backup from
the device you actually used:

1. On that one device: **Personal Study ▸ ⤒ ▸ Create Backup**.
2. Open the page. It already shows your library — how many highlights and notes
   are in it, and which devices it draws on.
3. Add that one backup and tap **Add to the remembered library**.
4. Save the result and restore it wherever you want it.

You can add as many devices as you like: a phone, a tablet, a second tablet, a
computer. Each one just needs to have contributed a backup once.

### Skipping the export tap, with a Shortcut

Making a backup by hand is the only part of this that still needs the app. It
can be skipped, because JW Library lets the Files app see its own library.

Look in **Files ▸ On My iPhone ▸ JW Library**. There is a folder called
**Userdata** — that is the live library. A Shortcut can copy it out on a
schedule, so a fresh copy lands in your shared folder every night without you
touching anything:

1. Open **Shortcuts** and create a new shortcut.
2. **Get Contents of Folder** — pick `On My iPhone ▸ JW Library ▸ Userdata`.
3. **Make Archive** — this produces one `.zip`.
4. **Save File** — into your shared folder, with *Overwrite If File Exists* on.
   Give it a name that says which device it is, like `iPhone Userdata.zip`.
5. In the **Automation** tab, run that shortcut daily at a time your device is
   usually idle.

Then add that `.zip` here like any other backup — the page reads it and shows
which device it came from.

> **Copy the whole folder, not just `userData.db`.** On a real device that file
> can be a nearly empty shell, with everything living in the `userData.db-wal`
> beside it. A copy of the database on its own looks like a library with nothing
> in it, and restoring that would wipe the real one. Archiving the whole folder
> takes everything, and this page puts it back together correctly.

It is safe to run while JW Library is open. If a copy is taken mid-write, the
page uses the last completed save and ignores the unfinished part.

**Restoring still needs you.** Nothing can put a library back onto a phone
without going through the app, and that is the right place for the line to be —
restoring replaces everything, and it should be deliberate.

### More than one person

If a tablet is shared, or you help someone else with theirs, tap **Manage** at
the top and **Add someone else**. Each person keeps their own library and their
own devices, and they never mix.

### Where all this is kept

On your device, in the browser, and nowhere else. Nothing is uploaded. With the
page open you can turn the internet off entirely and it still works.

The browser may clear what it remembers if the device runs very low on space —
the page tells you how much room it is using. Nothing is lost when that happens
as long as you have saved the combined file, which is why step 5 matters. To
clear it yourself, tap **Forget it**.

> **Restoring replaces** what is on that device. That is the point — the combined
> file has everything from every device — but it is why you restore the
> *combined* file and never one device's own backup. Keep your original backups
> until you have checked that everything is there.

## Setting up the computer app

### 1. Make a folder your devices share

Any folder that iCloud Drive, Google Drive or Dropbox already syncs will do.
Call it something like **JW backups**. This is where every device's backup goes,
and where the merged one comes back.

### 2. Open jwsync

Download the project from GitHub (green **Code** button ▸ **Download ZIP**),
unzip it, open the `launchers` folder and double-click:

- **Mac** — `Start jwsync (Mac).command`
- **Windows** — `Start jwsync (Windows).bat`

A window opens in your browser. Leave the small black window open behind it;
closing that one stops jwsync.

> **The first time on a Mac**, you may see *"cannot be opened because it is from
> an unidentified developer."* Right-click the file, choose **Open**, then click
> **Open** again. You only ever do that once.

Macs already have everything jwsync needs. On Windows, if it tells you Python is
missing, install it from python.org and tick **Add Python to PATH** during the
installation.

## Each time you want to sync

### On your phone or tablet

1. Open JW Library.
2. Go to **Personal Study**.
3. Tap the **⤒** icon at the top right.
4. Tap **Create Backup**.
5. Save it into your shared folder (**Files ▸ iCloud Drive ▸ JW backups**).

Do this on every device where you have made notes or highlights since last time.

### On your computer

1. Open jwsync (double-click the launcher).
2. Type or paste the path of your shared folder and click **Scan**. It remembers
   it for next time.
3. If JW Library is installed on this computer, you will see a card for it. Click
   **Add it to the folder** — that takes the place of doing Create Backup here.
4. Click **Merge selected**.

It tells you when it is done, and checks its own work: *"Merged and verified —
every item from every backup is in …"*. That word **verified** means it went
back through every note, highlight, bookmark, tag and playlist in every backup
and confirmed each one is in the merged file.

### Back on your phone or tablet

1. Wait for the merged file to appear in your shared folder.
2. In JW Library: **Personal Study ▸ ⤒ ▸ Restore Backup**.
3. Choose the merged file.

> **Restoring replaces what is on that device.** That is the point — the merged
> file has everything from every device — but it is why you always restore the
> *merged* file and never one device's own backup.

### And on the computer

If JW Library is installed here, quit it completely, then click **Put the merged
library back into it**. Your current library is copied aside first, into a folder
called `jwsync-safety-copies` in your home folder.

## Letting it run by itself

Once you trust it, jwsync can watch the folder and merge on its own, so the only
thing left is the tapping on your phone. In a Terminal or Command Prompt:

```bash
jwsync watch "~/JW backups" --with-local --push-local
```

To have that start every time you log in:

```bash
jwsync install-agent "~/JW backups"
```

That writes the setup and prints the one command that switches it on. It does not
switch it on by itself.

## Things worth knowing

**Deleting is different from adding.** jwsync only ever adds. If you delete a
note on your phone and then merge with an older tablet backup that still has it,
the note comes back. Delete it everywhere, or delete it after merging.

**A study answer that differs.** If you answered the same study question
differently on two devices, jwsync cannot tell which is newer — JW Library does
not record that. It keeps the answer from your most recent backup and says so in
the report.

**Bookmarks.** JW Library allows ten per publication. If merging would need an
eleventh, jwsync says which one it could not fit rather than dropping it quietly.

**A backup that has not downloaded yet.** If iCloud shows a file as a cloud icon
rather than a real file, jwsync waits for it instead of merging a half-downloaded
file. Right-click the folder and choose **Keep Downloaded** to avoid this.

**Both devices must run the same JW Library version.** If one is much older,
jwsync will say the backups use different schema versions. Update both and export
again.

## If something goes wrong

Nothing you had is lost — your original backups are untouched, and every merge is
kept in the `_jwsync_history` folder alongside the merged file.

- **A device looks wrong after restoring** — restore that device's own original
  backup, which is still in your shared folder.
- **The computer's library looks wrong** — the previous one is in
  `jwsync-safety-copies` in your home folder, in a dated folder.
- **jwsync says something is missing** — do not restore that file. The report
  names exactly what it could not find; that is worth reporting as a bug.
