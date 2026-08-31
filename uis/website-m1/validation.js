const form = document.getElementById("application-form");
const formStatus = document.getElementById("form-status");

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const phonePattern = /^\+?[0-9\s\-()]{7,20}$/;
const urlPattern = /^https?:\/\/.+\..+/;

const fieldConfig = {
  full_name: {
    input: document.getElementById("full_name"),
    error: document.getElementById("full_name-error"),
    required: true,
    validate: (value) => {
      if (!value.trim()) return "Full name is required.";
      if (value.trim().length < 2) return "Enter your full name.";
      return null;
    },
  },
  email: {
    input: document.getElementById("email"),
    error: document.getElementById("email-error"),
    required: true,
    validate: (value) => {
      if (!value.trim()) return "Email is required.";
      if (!emailPattern.test(value)) return "Enter a valid email address.";
      return null;
    },
  },
  phone: {
    input: document.getElementById("phone"),
    error: document.getElementById("phone-error"),
    required: true,
    validate: (value) => {
      if (!value.trim()) return "Phone number is required.";
      if (!phonePattern.test(value)) return "Enter a valid phone number.";
      return null;
    },
  },
  position: {
    input: document.getElementById("position"),
    error: document.getElementById("position-error"),
    required: true,
    validate: (value) => {
      if (!value) return "Please select a position.";
      return null;
    },
  },
  experience_years: {
    input: document.getElementById("experience_years"),
    error: document.getElementById("experience_years-error"),
    required: true,
    validate: (value) => {
      if (value === "") return "Years of experience is required.";
      const num = Number(value);
      if (Number.isNaN(num) || num < 0) return "Enter 0 or more years.";
      return null;
    },
  },
  linkedin_url: {
    input: document.getElementById("linkedin_url"),
    error: document.getElementById("linkedin_url-error"),
    required: false,
    validate: (value) => {
      if (!value.trim()) return null;
      if (!urlPattern.test(value)) return "Enter a valid URL (starting with http:// or https://).";
      return null;
    },
  },
  cv_url: {
    input: document.getElementById("cv_url"),
    error: document.getElementById("cv_url-error"),
    required: false,
    validate: (value) => {
      if (!value.trim()) return null;
      if (!urlPattern.test(value)) return "Enter a valid URL (starting with http:// or https://).";
      return null;
    },
  },
};

function showFieldError(fieldName, message) {
  const field = fieldConfig[fieldName];
  if (message) {
    field.input.setAttribute("aria-invalid", "true");
    field.error.textContent = message;
  } else {
    field.input.setAttribute("aria-invalid", "false");
    field.error.textContent = "";
  }
}

function validateField(fieldName) {
  const field = fieldConfig[fieldName];
  const message = field.validate(field.input.value);
  showFieldError(fieldName, message);
  return message === null;
}

Object.keys(fieldConfig).forEach((fieldName) => {
  const field = fieldConfig[fieldName];
  field.input.addEventListener("blur", () => validateField(fieldName));
  field.input.addEventListener("input", () => {
    if (field.input.getAttribute("aria-invalid") === "true") {
      validateField(fieldName);
    }
  });
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  formStatus.textContent = "";

  const fieldNames = Object.keys(fieldConfig);
  const invalidFields = fieldNames.filter((fieldName) => !validateField(fieldName));

  if (invalidFields.length > 0) {
    formStatus.textContent = "Please correct the highlighted fields before submitting.";
    formStatus.classList.remove("text-[#5f5a54]");
    formStatus.classList.add("text-[#b3261e]");
    fieldConfig[invalidFields[0]].input.focus();
    return;
  }

  formStatus.classList.remove("text-[#b3261e]");
  formStatus.classList.add("text-[#5f5a54]");
  formStatus.textContent = "Thanks! Your application was submitted successfully.";
  form.reset();
  fieldNames.forEach((fieldName) => showFieldError(fieldName, null));
});