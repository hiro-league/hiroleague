// An SVG string as an image address (`<img src>`), for SVG made elsewhere (e.g. a QR
// code): an image can't run scripts or touch the page, unlike SVG inserted as markup. SVG written for
// inline use often leaves out its namespace, which an image needs, so it is added.
const NS = 'http://www.w3.org/2000/svg';

export function svgImage(svg: string): string {
	const withNs = /<svg[^>]*\sxmlns=/.test(svg) ? svg : svg.replace('<svg', `<svg xmlns="${NS}"`);
	return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(withNs)}`;
}
