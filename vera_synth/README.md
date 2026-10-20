# vera_synth

Several accounts, each posting on its own. Every account is one folder here, with its own creative rules, keys, runs, and Instagram credentials. `vera_synth_photo` is the first account: photographer-style portraits.

```
vera_synth/
  vera_synth_photo/     photography account
    account.json        name, post hour, AI label
    queue/              carousels waiting to publish
    runs/               generated portraits
```

A new account is a sibling folder, named for what it posts, with the same shape: a direction file, a `.env` that is never committed, a `runs/` folder, and its own queue. It does not share another account's token or history.

`vera_synth_photo` is documented in `vera_synth_photo/README.md`.
