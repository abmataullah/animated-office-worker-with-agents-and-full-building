# ABM Office

A pixel-art office that shows your PC workloads as workers at desks. ABM is the boss and hands out tasks.
Open `office-widget.html` in a browser. No build step.

## Two modes

**Simulated** (default). Workers run made-up jobs from the lists in `ROLES`. The status bar says SIMULATED.

**Live feed.** Run `node feed/pc-feed.js` and reload the page. The status bar switches to LIVE FEED and
only real jobs show up. Workers with nothing to do leave their desks. Use `?feed=http://host:port` to point
at another feed, or `?feed=off` to stay in simulation.

The feed has two sources:

1. A process scan for apps like Premiere, Photoshop, Excel and Dropbox (edit `RULES` in `feed/pc-feed.js`).
   This shows that an app is open, not that it is busy.
2. `POST http://localhost:8765/event` for everything else. Facebook ads, email tools and similar services
   cannot be detected from the OS, so the tool or automation has to report its own status:

```
curl -X POST localhost:8765/event -H 'content-type: application/json' \
  -d '{"id":"fb-1","cat":"ads","task":"Retargeting campaign","progress":40}'
```

Categories: `ads video design writing sheets backup email social media docs web data`.
Send `"status":"done"` to log a finish.
