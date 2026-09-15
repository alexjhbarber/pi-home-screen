window.translate = (key, values = {}) => {
  const text = window.i18n[key] || key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(values, name) ? values[name] : match
  ));
};
