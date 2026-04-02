import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Rocket, Menu, X } from 'lucide-react';

const Navbar: React.FC = () => {
  const location = useLocation();
  const [isOpen, setIsOpen] = React.useState(false);

  const isActive = (path: string) => location.pathname === path;

  const navLinks = [
    { name: 'Positive EV', path: '/positive-ev' },
    { name: 'Arbitrage', path: '/arbitrage' },
    { name: 'Current Markets', path: '/markets' },
    { name: 'Parlay Builder', path: '/parlay' },
  ];

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <div className="flex items-center">
            <Link to="/" className="flex items-center gap-2">
              <Rocket className="h-8 w-8 text-amber-500" />
              <span className="text-xl font-bold tracking-tight text-white">
                Sharp<span className="text-amber-500">Edge</span>
              </span>
            </Link>
            <div className="hidden md:block">
              <div className="ml-10 flex items-baseline space-x-4">
                {navLinks.map((link) => (
                  <Link
                    key={link.name}
                    to={link.path}
                    className={`rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                      isActive(link.path)
                        ? 'bg-zinc-800 text-amber-500'
                        : 'text-zinc-300 hover:bg-zinc-800 hover:text-white'
                    }`}
                  >
                    {link.name}
                  </Link>
                ))}
              </div>
            </div>
          </div>
          <div className="hidden md:block">
            <button className="rounded-full bg-amber-500 px-5 py-2 text-sm font-bold text-black transition-transform hover:scale-105 hover:bg-amber-400">
              Sign In
            </button>
          </div>
          <div className="-mr-2 flex md:hidden">
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="inline-flex items-center justify-center rounded-md bg-zinc-900 p-2 text-zinc-400 hover:bg-zinc-800 hover:text-white focus:outline-none"
            >
              {isOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {isOpen && (
        <div className="md:hidden">
          <div className="space-y-1 px-2 pb-3 pt-2 sm:px-3">
            {navLinks.map((link) => (
              <Link
                key={link.name}
                to={link.path}
                onClick={() => setIsOpen(false)}
                className={`block rounded-md px-3 py-2 text-base font-medium ${
                  isActive(link.path)
                    ? 'bg-zinc-900 text-amber-500'
                    : 'text-zinc-300 hover:bg-zinc-800 hover:text-white'
                }`}
              >
                {link.name}
              </Link>
            ))}
            <button className="mt-4 w-full rounded-md bg-amber-500 px-5 py-3 text-center text-base font-bold text-black hover:bg-amber-400">
              Sign In
            </button>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;