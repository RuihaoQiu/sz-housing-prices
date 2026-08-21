"""Helper: JS extraction code for Chrome-based scraping.

This module provides the JavaScript snippet and Python post-processing
used by the main leyoujia_scraper when running via Chrome automation.
"""

# JavaScript to inject into each listing page — extracts all listings from DOM.
EXTRACT_LISTINGS_JS = """
(() => {
  const items = document.querySelectorAll('li.item');
  const listings = [];
  items.forEach(item => {
    const detailLink = item.querySelector('a[href*="/zf/detail/"]');
    const btn = item.querySelector('div.im-zixun[data-price]');
    const xqLink = item.querySelector('a[href*="/xq/detail/"]');
    const tit = item.querySelector('p.tit a');
    const priceEl = item.querySelector('span.salePrice');
    const subareaLink = item.querySelector('a[href*="/zf/a3q"]');
    const districtLink = item.querySelector('a[href*="/zf/a"]');

    if (!detailLink) return;
    const idMatch = detailLink.href.match(/\\/zf\\/detail\\/(\\w+)/);
    if (!idMatch) return;

    const listing = { id: idMatch[1] };

    if (btn) {
      listing.price = Number(btn.dataset.price) || null;
      listing.rooms = Number(btn.dataset.room) || null;
      listing.halls = Number(btn.dataset.hall) || null;
      listing.area = Number(btn.dataset.area) || null;
      listing.community_id = Number(btn.dataset.lpid) || null;
      listing.house_id = Number(btn.dataset.fid || btn.dataset.houseid) || null;
      listing.orientation = btn.dataset.forward || null;
      listing.decoration = btn.dataset.fitment || null;
    }

    if (tit) {
      listing.title = tit.textContent.trim();
      if (listing.title.startsWith('整租')) listing.rental_type = '整租';
      else if (listing.title.startsWith('合租')) listing.rental_type = '合租';
    }

    if (xqLink) listing.community = xqLink.textContent.trim();
    if (priceEl) listing.price = listing.price || Number(priceEl.textContent.trim());
    if (subareaLink) listing.subarea = subareaLink.textContent.trim();

    // District from /zf/a{n}/ link (not sub-area)
    if (districtLink) {
      const dMatch = districtLink.href.match(/\\/zf\\/a\\d+\\/$/);
      if (dMatch) listing.district = districtLink.textContent.trim();
    }

    // Attribute rows
    const attrs = item.querySelectorAll('p.attr');
    const fullText = Array.from(attrs).map(a => a.textContent).join(' ');

    const layoutMatch = fullText.match(/(\\d+室\\d+厅(?:\\d+卫)?)/);
    if (layoutMatch) listing.layout = layoutMatch[1];

    const floorMatch = fullText.match(/([低中高]楼层)\\(共(\\d+)层\\)/);
    if (floorMatch) {
      listing.floor = floorMatch[1];
      listing.total_floors = Number(floorMatch[2]);
    }

    const yearMatch = fullText.match(/(\\d{4})年建成/);
    if (yearMatch) listing.year_built = Number(yearMatch[1]);

    const areaMatch = fullText.match(/建筑面积([\\d.]+)㎡/);
    if (areaMatch) listing.area = listing.area || Number(areaMatch[1]);

    // Payment terms
    const sub = item.querySelector('p.sub');
    if (sub) {
      const payMatch = sub.textContent.match(/(押[一二三]付[一二三])/);
      if (payMatch) listing.payment = payMatch[1];
    }

    // Metro and tags
    const labs = item.querySelectorAll('p.labs span.lab');
    const tags = [];
    labs.forEach(lab => {
      const t = lab.textContent.trim();
      const mMatch = t.match(/距(.+?线.+?站)(\\d+)米/);
      if (mMatch) {
        listing.metro_station = mMatch[1];
        listing.metro_distance = Number(mMatch[2]);
      } else if (t) {
        tags.push(t);
      }
    });
    if (tags.length) listing.tags = tags;

    // Computed
    if (listing.price && listing.area) {
      listing.price_per_sqm = Math.round(listing.price / listing.area * 10) / 10;
    }

    listings.push(listing);
  });

  // Check for next page link
  const nextLink = document.querySelector('a.fy_nextpage');
  const hasNext = !!nextLink || !!Array.from(document.querySelectorAll('a')).find(
    a => a.textContent.includes('下一页')
  );

  // Total count
  const bodyText = document.body.textContent;
  const countMatch = bodyText.match(/共为您找到.*?(\\d[\\d,]*)\\s*套/);
  const totalCount = countMatch ? Number(countMatch[1].replace(/,/g, '')) : null;

  return JSON.stringify({ listings, hasNext, totalCount });
})()
"""
