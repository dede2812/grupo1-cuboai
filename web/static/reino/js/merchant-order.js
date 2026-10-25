(() => {
  const source = document.getElementById('order-transition-options');
  const field = document.getElementById('field');
  const target = document.getElementById('to');
  if (!source || !field || !target) return;
  const choices = JSON.parse(source.textContent);
  const update = () => {
    const options = choices[field.value] || [];
    target.replaceChildren(...options.map(item => new Option(item.label, item.value)));
    if (!options.length) target.add(new Option('Sin cambios disponibles', ''));
    target.disabled = !options.length;
    field.form.querySelector('button[type="submit"]').disabled = !options.length;
  };
  field.addEventListener('change', update);
  update();
})();
