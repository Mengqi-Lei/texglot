/** macOS native menus read list-style-image without the XUL iconic class.
 * Zotero deliberately hides library-menu icons when that class is present.
 */
export function setMenuIcon(element: HTMLElement, iconURI: string | undefined, isMac: boolean): void {
  if (!iconURI) return;
  element.classList.toggle("menuitem-iconic", !isMac);
  element.style.setProperty("list-style-image", `url("${iconURI}")`);
}
