# 🤝 Contributing to Store Intelligence System

Thank you for your interest in contributing to the Store Intelligence System! This document provides guidelines and information for contributors.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)
- [Project Structure](#project-structure)

---

## 📜 Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inspiring community for all. Please be respectful and constructive in your interactions.

### Our Standards

- ✅ Use welcoming and inclusive language
- ✅ Be respectful of differing viewpoints
- ✅ Accept constructive criticism gracefully
- ✅ Focus on what is best for the community
- ❌ No harassment, trolling, or insulting comments
- ❌ No personal or political attacks

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Git
- Basic understanding of FastAPI and React

### Setup Development Environment

1. **Fork the repository**
   ```bash
   # Click "Fork" button on GitHub
   ```

2. **Clone your fork**
   ```bash
   git clone https://github.com/YOUR_USERNAME/Store-Intelligence-System.git
   cd Store-Intelligence-System
   ```

3. **Add upstream remote**
   ```bash
   git remote add upstream https://github.com/Kapilsharma72/Store-Intelligence-System.git
   ```

4. **Install dependencies**
   ```bash
   # Backend
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   
   # Frontend
   cd frontend
   npm install
   cd ..
   ```

5. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env with your local configuration
   ```

6. **Initialize database**
   ```bash
   alembic upgrade head
   ```

---

## 🔄 Development Workflow

### 1. Create a Feature Branch

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name
```

### Branch Naming Convention

- `feature/` - New features (e.g., `feature/add-export-api`)
- `bugfix/` - Bug fixes (e.g., `bugfix/fix-metrics-calculation`)
- `hotfix/` - Urgent fixes (e.g., `hotfix/security-patch`)
- `docs/` - Documentation (e.g., `docs/update-readme`)
- `refactor/` - Code refactoring (e.g., `refactor/optimize-queries`)
- `test/` - Test additions (e.g., `test/add-integration-tests`)

### 2. Make Your Changes

- Write clean, readable code
- Follow coding standards (see below)
- Add tests for new features
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run backend tests
pytest --cov=app tests/

# Run frontend tests (if applicable)
cd frontend
npm test
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "feat: add export to PDF functionality"
```

### 5. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 6. Create Pull Request

- Go to GitHub and create a Pull Request
- Fill in the PR template
- Link related issues
- Request review

---

## 💻 Coding Standards

### Python (Backend)

#### Style Guide

Follow **PEP 8** style guide:

```python
# Good
def calculate_conversion_rate(purchases: int, visitors: int) -> float:
    """Calculate conversion rate as a percentage.
    
    Args:
        purchases: Number of completed purchases
        visitors: Total number of unique visitors
        
    Returns:
        Conversion rate as a float between 0 and 100
    """
    if visitors == 0:
        return 0.0
    return (purchases / visitors) * 100


# Bad
def calc_conv(p,v):
    if v==0:return 0
    return p/v*100
```

#### Key Principles

- **Type hints**: Always use type hints
- **Docstrings**: Document all functions and classes
- **Naming**: Use descriptive names (`calculate_metrics` not `calc_m`)
- **Line length**: Max 100 characters
- **Imports**: Group and sort imports (stdlib, third-party, local)

#### Code Formatting

```bash
# Use black for formatting
pip install black
black app/

# Use isort for import sorting
pip install isort
isort app/

# Use flake8 for linting
pip install flake8
flake8 app/
```

### TypeScript/React (Frontend)

#### Style Guide

```typescript
// Good
interface StoreMetrics {
  storeId: string;
  uniqueVisitors: number;
  conversionRate: number;
  avgDwellSeconds: number;
}

const calculateConversionRate = (
  purchases: number,
  visitors: number
): number => {
  if (visitors === 0) return 0;
  return (purchases / visitors) * 100;
};


// Bad
const calc = (p, v) => {
  if (v == 0) return 0;
  return p / v * 100;
};
```

#### Key Principles

- **TypeScript**: Use strict mode, avoid `any`
- **Components**: Functional components with hooks
- **Naming**: PascalCase for components, camelCase for functions
- **Props**: Define interfaces for all props
- **State**: Use appropriate hooks (useState, useEffect, etc.)

---

## 🧪 Testing Guidelines

### Backend Testing

#### Unit Tests

```python
# tests/test_metrics.py
import pytest
from app.metrics import calculate_conversion_rate


def test_conversion_rate_normal():
    """Test conversion rate with normal values."""
    result = calculate_conversion_rate(purchases=50, visitors=100)
    assert result == 50.0


def test_conversion_rate_zero_visitors():
    """Test conversion rate with zero visitors."""
    result = calculate_conversion_rate(purchases=0, visitors=0)
    assert result == 0.0


@pytest.mark.parametrize("purchases,visitors,expected", [
    (10, 100, 10.0),
    (25, 50, 50.0),
    (0, 100, 0.0),
])
def test_conversion_rate_parametrized(purchases, visitors, expected):
    """Test conversion rate with multiple scenarios."""
    result = calculate_conversion_rate(purchases, visitors)
    assert result == expected
```

#### Property-Based Tests

```python
from hypothesis import given, strategies as st


@given(
    purchases=st.integers(min_value=0, max_value=1000),
    visitors=st.integers(min_value=1, max_value=1000)
)
def test_conversion_rate_properties(purchases, visitors):
    """Test conversion rate properties."""
    result = calculate_conversion_rate(purchases, visitors)
    
    # Property: Result should be between 0 and 100
    assert 0 <= result <= 100
    
    # Property: More purchases should not decrease rate
    if purchases < visitors:
        higher_result = calculate_conversion_rate(purchases + 1, visitors)
        assert higher_result >= result
```

### Frontend Testing

```typescript
// tests/MetricsCard.test.tsx
import { render, screen } from '@testing-library/react';
import MetricsCard from '../components/MetricsCard';


describe('MetricsCard', () => {
  it('renders metric value correctly', () => {
    render(
      <MetricsCard 
        title="Conversion Rate" 
        value={45.5} 
        unit="%" 
      />
    );
    
    expect(screen.getByText('45.5%')).toBeInTheDocument();
  });
  
  it('handles zero values', () => {
    render(
      <MetricsCard 
        title="Visitors" 
        value={0} 
      />
    );
    
    expect(screen.getByText('0')).toBeInTheDocument();
  });
});
```

### Test Coverage

- Aim for **80%+ code coverage**
- All new features must include tests
- Bug fixes should include regression tests

```bash
# Check coverage
pytest --cov=app --cov-report=html tests/

# View coverage report
open htmlcov/index.html
```

---

## 📝 Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```bash
# Good commits
git commit -m "feat(api): add PDF export endpoint"
git commit -m "fix(metrics): correct conversion rate calculation"
git commit -m "docs(readme): update installation instructions"
git commit -m "test(funnel): add property-based tests"

# Bad commits
git commit -m "fixed stuff"
git commit -m "updates"
git commit -m "WIP"
```

### Detailed Commit

```bash
git commit -m "feat(analytics): add real-time visitor tracking

- Implement WebSocket connection for live updates
- Add Redis pub/sub for event broadcasting
- Update frontend to display real-time metrics
- Add tests for WebSocket functionality

Closes #123"
```

---

## 🔀 Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] No merge conflicts with main branch
- [ ] Commit messages follow guidelines

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe testing performed

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Tests pass
- [ ] Documentation updated
- [ ] Code follows style guide
- [ ] Self-review completed

## Related Issues
Closes #123
```

### Review Process

1. **Automated Checks**: CI/CD runs tests and linting
2. **Code Review**: At least one maintainer reviews
3. **Feedback**: Address review comments
4. **Approval**: Maintainer approves PR
5. **Merge**: Maintainer merges to main

### After Merge

- Delete your feature branch
- Update your local main branch
- Close related issues

---

## 📂 Project Structure

### Backend (`app/`)

```
app/
├── main.py              # FastAPI app entry point
├── database.py          # Database configuration
├── models.py            # SQLAlchemy models
├── ingestion.py         # Event ingestion
├── metrics.py           # Metrics calculation
├── funnel.py            # Funnel analysis
├── heatmap.py           # Heatmap generation
├── anomalies.py         # Anomaly detection
├── videos.py            # Video management
├── auth.py              # Authentication
└── ...
```

### Frontend (`frontend/src/`)

```
frontend/src/
├── components/          # Reusable components
│   ├── MetricsCard.tsx
│   ├── Heatmap.tsx
│   └── ...
├── pages/              # Page components
│   ├── Dashboard.tsx
│   ├── Analytics.tsx
│   └── ...
├── services/           # API services
│   └── api.ts
├── types/              # TypeScript types
│   └── index.ts
└── App.tsx             # Main app
```

---

## 🎯 Areas for Contribution

### High Priority

- [ ] Mobile responsive design improvements
- [ ] Additional anomaly detection algorithms
- [ ] Performance optimization for large datasets
- [ ] Multi-language support (i18n)
- [ ] Advanced filtering and search

### Medium Priority

- [ ] Export to additional formats (CSV, JSON)
- [ ] Email/SMS alert notifications
- [ ] Custom dashboard widgets
- [ ] Historical trend analysis
- [ ] A/B testing features

### Documentation

- [ ] API usage examples
- [ ] Video tutorials
- [ ] Architecture diagrams
- [ ] Deployment guides
- [ ] Troubleshooting guides

---

## 💬 Communication

### Questions?

- **GitHub Discussions**: For general questions
- **GitHub Issues**: For bugs and feature requests
- **Email**: For private inquiries

### Stay Updated

- Watch the repository for updates
- Check GitHub Discussions regularly
- Review open issues and PRs

---

## 🏆 Recognition

Contributors will be:
- Listed in CONTRIBUTORS.md
- Mentioned in release notes
- Credited in documentation

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing! 🎉**

Your contributions help make this project better for everyone.
